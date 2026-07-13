from django.core.exceptions import PermissionDenied


class TeacherAssignmentRequiredMixin:
    """Mixin for views that require a teacher to be assigned to a specific subject/class/session.
    
    Usage: Override get_subject(), get_school_class(), get_session() in your view,
    and this mixin will verify the teacher has an assignment before the view is called.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not self._is_teacher_assigned():
            raise PermissionDenied("You are not assigned to this subject/class/session.")
        return super().dispatch(request, *args, **kwargs)
    
    def _is_teacher_assigned(self):
        """Check if the current user (teacher) is assigned to the subject/class/session."""
        from .permissions import teacher_can_access
        
        subject = self.get_subject()
        school_class = self.get_school_class()
        session = self.get_session()
        
        if not all([subject, school_class, session]):
            return False
        
        return teacher_can_access(self.request.user, subject, school_class, session)
    
    def get_subject(self):
        """Override in your view to return the Subject instance."""
        raise NotImplementedError
    
    def get_school_class(self):
        """Override in your view to return the SchoolClass instance."""
        raise NotImplementedError
    
    def get_session(self):
        """Override in your view to return the AcademicSession instance."""
        raise NotImplementedError
