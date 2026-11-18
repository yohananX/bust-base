"""Guided next-session preparation views for school administrators."""

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import AcademicSession
from students.models import (
    AcademicStage,
    ClassOffering,
    SchoolClass,
    SessionPreparation,
    StudentSessionMovement,
)
from students.progression import (
    TERM_NAMES,
    confirm_session_preparation,
    create_session_preparation,
    generate_progression_proposals,
    get_or_create_session_preparation,
    preparation_summary,
    set_preparation_offerings,
    update_preparation_schedule,
    update_progression_configuration,
    update_student_movement,
)


def _error_text(exc):
    if hasattr(exc, 'message_dict'):
        return ' '.join(
            str(message)
            for field_messages in exc.message_dict.values()
            for message in field_messages
        )
    return ' '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)


def _preparation(request, pk):
    return get_object_or_404(
        SessionPreparation.objects.select_related(
            'source_session', 'target_session', 'created_by', 'confirmed_by'
        ),
        school=request.school,
        pk=pk,
    )


def _progression_mappings(request, school):
    stages = list(AcademicStage.objects.filter(school=school))
    classes = list(SchoolClass.objects.filter(school=school))
    stage_mapping = {
        stage.pk: request.POST.get(f'stage_next_{stage.pk}', '')
        for stage in stages
    }
    class_mapping = {
        school_class.pk: request.POST.get(f'class_next_{school_class.pk}', '')
        for school_class in classes
    }
    return stage_mapping, class_mapping


def _term_specs(post):
    prefixes = ('first', 'second', 'third')
    return [
        {
            'name': name,
            'start_date': parse_date(post.get(f'{prefix}_term_start', '')),
            'end_date': parse_date(post.get(f'{prefix}_term_end', '')),
        }
        for name, prefix in zip(TERM_NAMES, prefixes)
    ]


class ProgressionConfigurationView(RoleRequiredMixin, View):
    """Manage the permanent stage and class progression graphs."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        context = {
            'stages': AcademicStage.objects.filter(
                school=request.school
            ).select_related('next_stage'),
            'classes': SchoolClass.objects.filter(
                school=request.school
            ).select_related('academic_stage', 'next_class__academic_stage'),
        }
        return render(request, 'school_admin/progression_configuration.html', context)

    def post(self, request):
        stage_mapping, class_mapping = _progression_mappings(request, request.school)
        try:
            changed_stages, changed_classes = update_progression_configuration(
                request.school, stage_mapping, class_mapping
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                f'Permanent progression saved: {changed_stages} stage and '
                f'{changed_classes} class relationship(s) updated.',
            )
        return redirect('school_admin:progression_configuration')


class SessionPreparationCreateView(RoleRequiredMixin, View):
    """Create a future session with explicitly configured terms."""

    allowed_roles = [Roles.ADMIN]

    def _context(self, request, data=None):
        sessions = AcademicSession.objects.filter(school=request.school).order_by('-start_date')
        source = sessions.filter(is_current=True).first() or sessions.first()
        initial = {}
        if source:
            def next_year(value):
                try:
                    return value.replace(year=value.year + 1)
                except ValueError:  # February 29 -> February 28.
                    return value.replace(year=value.year + 1, day=28)

            session_start = next_year(source.start_date)
            session_end = next_year(source.end_date)
            total_days = (session_end - session_start).days
            third = max(total_days // 3, 1)
            initial = {
                'source_session_id': source.pk,
                'start_date': session_start,
                'end_date': session_end,
                'first_term_start': session_start,
                'first_term_end': session_start + timedelta(days=third),
                'second_term_start': session_start + timedelta(days=third + 1),
                'second_term_end': session_start + timedelta(days=2 * third),
                'third_term_start': session_start + timedelta(days=2 * third + 1),
                'third_term_end': session_end,
            }
        return {
            'sessions': sessions,
            'initial': initial,
            'form_data': data,
        }

    def get(self, request):
        return render(
            request,
            'school_admin/session_preparation_create.html',
            self._context(request),
        )

    def post(self, request):
        source = AcademicSession.objects.filter(
            school=request.school, pk=request.POST.get('source_session_id')
        ).first()
        if source is None:
            messages.error(request, 'Select a valid source session.')
            return render(
                request,
                'school_admin/session_preparation_create.html',
                self._context(request, request.POST),
            )
        try:
            preparation = create_session_preparation(
                school=request.school,
                source_session=source,
                name=request.POST.get('name', '').strip(),
                start_date=parse_date(request.POST.get('start_date', '')),
                end_date=parse_date(request.POST.get('end_date', '')),
                term_specs=_term_specs(request.POST),
                created_by=request.user,
            )
        except (ValidationError, TypeError) as exc:
            messages.error(request, _error_text(exc))
            return render(
                request,
                'school_admin/session_preparation_create.html',
                self._context(request, request.POST),
            )
        messages.success(request, 'Next session created. Continue with class offerings.')
        return redirect('school_admin:session_preparation_detail', pk=preparation.pk)


class SessionPreparationStartView(RoleRequiredMixin, View):
    """Start preparation for a future session that already exists."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, session_pk):
        target = get_object_or_404(
            AcademicSession, school=request.school, pk=session_pk
        )
        existing = SessionPreparation.objects.filter(
            school=request.school, target_session=target
        ).first()
        if existing:
            return redirect('school_admin:session_preparation_detail', pk=existing.pk)
        sources = AcademicSession.objects.filter(
            school=request.school, start_date__lt=target.start_date
        ).order_by('-start_date')
        return render(request, 'school_admin/session_preparation_start.html', {
            'target_session': target,
            'source_sessions': sources,
            'default_source': sources.filter(is_current=True).first() or sources.first(),
        })

    def post(self, request, session_pk):
        target = get_object_or_404(
            AcademicSession, school=request.school, pk=session_pk
        )
        source = AcademicSession.objects.filter(
            school=request.school, pk=request.POST.get('source_session_id')
        ).first()
        if source is None:
            messages.error(request, 'Select a valid source session.')
            return redirect(
                'school_admin:session_preparation_start', session_pk=target.pk
            )
        try:
            preparation, created = get_or_create_session_preparation(
                school=request.school,
                source_session=source,
                target_session=target,
                created_by=request.user,
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
            return redirect(
                'school_admin:session_preparation_start', session_pk=target.pk
            )
        if created:
            messages.success(request, 'Session preparation started.')
        return redirect('school_admin:session_preparation_detail', pk=preparation.pk)


class SessionPreparationDetailView(RoleRequiredMixin, View):
    """Render all guided preparation steps and the final review."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        preparation = _preparation(request, pk)
        classes = list(
            SchoolClass.objects.filter(school=request.school).select_related(
                'academic_stage', 'next_class__academic_stage'
            )
        )
        offerings = list(
            ClassOffering.objects.filter(
                school=request.school,
                academic_session=preparation.target_session,
            ).select_related('school_class__academic_stage')
        )
        offered_class_ids = {offering.school_class_id for offering in offerings}
        movements = list(
            StudentSessionMovement.objects.filter(
                school=request.school, preparation=preparation
            ).select_related(
                'student__user',
                'source_enrollment__school_class',
                'proposed_class',
                'destination_class',
                'preparation__target_session',
            )
        )
        counts, movements = preparation_summary(preparation, movements)
        return render(request, 'school_admin/session_preparation_detail.html', {
            'preparation': preparation,
            'terms': preparation.target_session.terms.order_by('start_date'),
            'stages': AcademicStage.objects.filter(
                school=request.school
            ).select_related('next_stage'),
            'classes': classes,
            'offering_classes': [
                school_class for school_class in classes
                if school_class.is_active or school_class.pk in offered_class_ids
            ],
            'offerings': offerings,
            'offered_class_ids': offered_class_ids,
            'movements': movements,
            'counts': counts,
            'movement_actions': StudentSessionMovement.Action.choices,
            'is_draft': preparation.status == SessionPreparation.Status.DRAFT,
        })


class PreparationScheduleUpdateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        preparation = _preparation(request, pk)
        try:
            update_preparation_schedule(
                preparation=preparation,
                start_date=parse_date(request.POST.get('start_date', '')),
                end_date=parse_date(request.POST.get('end_date', '')),
                term_specs=_term_specs(request.POST),
            )
        except (ValidationError, TypeError) as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(request, 'Session and term dates updated.')
        return redirect('school_admin:session_preparation_detail', pk=pk)


class PreparationOfferingsUpdateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        preparation = _preparation(request, pk)
        try:
            created, selected = set_preparation_offerings(
                preparation=preparation,
                class_ids=request.POST.getlist('class_ids'),
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                f'{selected} class offering(s) selected; {created} created.',
            )
        return redirect('school_admin:session_preparation_detail', pk=pk)


class PreparationProgressionUpdateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        preparation = _preparation(request, pk)
        if preparation.status != SessionPreparation.Status.DRAFT:
            messages.error(request, 'Confirmed preparations are read-only.')
            return redirect('school_admin:session_preparation_detail', pk=pk)
        stage_mapping, class_mapping = _progression_mappings(request, request.school)
        try:
            changed_stages, changed_classes = update_progression_configuration(
                request.school, stage_mapping, class_mapping
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                f'Permanent progression saved ({changed_stages} stage, '
                f'{changed_classes} class change(s)). Regenerate proposals to apply it.',
            )
        return redirect('school_admin:session_preparation_detail', pk=pk)


class PreparationGenerateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        preparation = _preparation(request, pk)
        try:
            created, refreshed = generate_progression_proposals(preparation)
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(
                request,
                f'Proposals generated: {created} new and {refreshed} refreshed.',
            )
        return redirect('school_admin:session_preparation_detail', pk=pk)


class PreparationMovementUpdateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk, movement_pk):
        preparation = _preparation(request, pk)
        movement = get_object_or_404(
            StudentSessionMovement,
            school=request.school,
            preparation=preparation,
            pk=movement_pk,
        )
        destination = None
        destination_id = request.POST.get('destination_class_id')
        if destination_id:
            destination = SchoolClass.objects.filter(
                school=request.school, pk=destination_id
            ).first()
        try:
            update_student_movement(
                movement=movement,
                action=request.POST.get('action', ''),
                destination_class=destination,
                note=request.POST.get('note', ''),
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(request, 'Student movement updated.')
        return redirect('school_admin:session_preparation_detail', pk=pk)


class PreparationConfirmView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        preparation = _preparation(request, pk)
        try:
            result = confirm_session_preparation(
                preparation=preparation, confirmed_by=request.user
            )
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            if result.already_confirmed:
                messages.info(request, 'This preparation was already confirmed; no duplicates were created.')
            else:
                messages.success(
                    request,
                    f'Preparation confirmed: {result.enrolled} enrolled, '
                    f'{result.withdrawn} withdrawn, {result.excluded} excluded.',
                )
        return redirect('school_admin:session_preparation_detail', pk=pk)
