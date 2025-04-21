from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from core.models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'is_active', 'is_staff', 'is_moderator', 'is_admin', 'web_login_enabled', 'date_joined')
    list_filter = ('is_active', 'is_staff', 'is_moderator', 'is_admin', 'web_login_enabled')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Contact Info', {'fields': ('email', 'preferred_contact_method')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'timezone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_moderator', 'is_admin', 'web_login_enabled', 'groups', 'user_permissions')}),
        ('MFA', {'fields': ('mfa_enabled', 'mfa_secret')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
    ) 