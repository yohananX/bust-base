"""Fee category CRUD for school admin portal."""
from django.shortcuts import render
from django.contrib import messages
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from fees.models import FeeCategory, InvoiceLineItem
from .mixins import AdminCreateView, AdminDeleteView, AdminUpdateView
from .forms import FeeCategoryForm


class FeeCategoryListView(RoleRequiredMixin, View):
    """List fee categories."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        categories = FeeCategory.objects.filter(school=school).order_by('name')
        return render(request, 'school_admin/fee_category_list.html', {
            'categories': categories,
        })


class FeeCategoryCreateView(AdminCreateView):
    """Create a new fee category."""
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'school_admin/fee_category_form.html'
    success_url = 'school_admin:fee_category_list'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['school'] = self.request.school
        return kwargs

    def form_valid(self, form):
        category = form.save(commit=False)
        category.school = self.request.school
        category.save()
        messages.success(self.request, f'Category "{category.name}" created successfully.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = False
        return context


class FeeCategoryEditView(AdminUpdateView):
    """Edit an existing fee category."""
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'school_admin/fee_category_form.html'
    success_url = 'school_admin:fee_category_list'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['school'] = self.request.school
        return kwargs

    def form_valid(self, form):
        category = form.save(commit=False)
        category.school = self.request.school
        category.save()
        messages.success(self.request, f'Category "{category.name}" updated successfully.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        return context


class FeeCategoryDeleteView(AdminDeleteView):
    """Delete a fee category with confirmation."""
    model = FeeCategory
    template_name = 'school_admin/fee_category_confirm_delete.html'
    success_url = 'school_admin:fee_category_list'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.object
        context['price_count'] = FeePrice.objects.filter(category=category).count()
        context['line_item_count'] = InvoiceLineItem.objects.filter(category=category).count()
        return context

    def post(self, request, *args, **kwargs):
        category = self.get_object()
        if FeePrice.objects.filter(category=category).exists():
            messages.error(request, 'Cannot delete — assigned to fee prices.')
            return redirect('school_admin:fee_category_list')
        messages.success(request, f'Category "{category.name}" deleted successfully.')
        return category.delete() or redirect(self.get_success_url())
