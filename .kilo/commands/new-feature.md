# Command: Add a New Feature

Use this when the user asks to add a new feature (CRUD, workflow, etc.).

## Workflow

1. **Models**: Define in `<app>/models.py`
   - Inherit `TenantScopedModel`
   - Add `__str__` method
   - Add `Meta` class with `verbose_name`, `ordering`
   - Run `makemigrations`

2. **Admin**: Register in `<app>/admin.py`
   - `list_display`, `list_filter`, `search_fields`
   - Add custom actions if needed

3. **Views**: Create in `<app>/views.py`
   - Use `RoleRequiredMixin` with appropriate `allowed_roles`
   - Scope all queries by `school=request.school`
   - Use `get_object_or_404` with school scoping
   - Use `messages` for user feedback

4. **URLs**: Add to `<app>/urls.py`
   - Use `app_name = '<app>'`
   - Use snake_case names

5. **Templates**: Create in `templates/<app>/`
   - Extend `base.html`
   - Use Tailwind CSS classes
   - Include Lucide icons via `data-lucide`

6. **Tests**: Add to `<app>/tests.py`
   - Test authenticated access
   - Test unauthorized access (wrong role)
   - Test school scoping (cross-school isolation)
   - Test CRUD operations

7. **Notifications**: If the feature creates events, add `notify()` calls
   - Use `channel='IN_APP'` unless email/SMS is explicitly requested
   - Use reference strings for dedup
   - Guard with `if guardian_link:` before notifying

## Example: Adding a simple model + CRUD

```python
# models.py
class Item(TenantScopedModel):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']

# admin.py
@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'school']
    list_filter = ['school']

# views.py
class ItemListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]
    def get(self, request):
        items = Item.objects.filter(school=request.school)
        return render(request, 'app/item_list.html', {'items': items})

# urls.py
urlpatterns = [
    path('items/', ItemListView.as_view(), name='item_list'),
]
```
