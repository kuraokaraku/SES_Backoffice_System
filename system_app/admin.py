# Register your models here.
from django.contrib import admin
from .models import (
    Freelancer, MonthlyProcess, TaskStatus, LegacyTaskStatus,
    ContactEntity, EntityContactPerson, Assignment, ServiceContract
)

@admin.register(Freelancer)
class FreelancerAdmin(admin.ModelAdmin):
    list_display = ('name', 'client_name', 'base_unit_price', 'lower_limit_hours', 'upper_limit_hours')
    fieldsets = (
        ("基本情報", {
            'fields': ('name', 'email', 'client_name', 'project_name')
        }),
        ("精算条件（自動計算用）", {
            'fields': (
                'base_unit_price',
                'lower_limit_hours',
                'upper_limit_hours',
                'deduction_unit_price',
                'overtime_unit_price'
            )
        }),
        ("契約期間", {
            'fields': ('contract_start', 'contract_end')
        }),
    )

@admin.register(MonthlyProcess)
class MonthlyProcessAdmin(admin.ModelAdmin):
    list_display = ('year_month', 'is_completed')
    readonly_fields = ('is_completed',)

@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ('month', 'assignment', 'timesheet_status', 'invoice_status', 'purchase_order_status')
    list_filter = ('month', 'timesheet_status', 'invoice_status', 'purchase_order_status')

@admin.register(LegacyTaskStatus)
class LegacyTaskStatusAdmin(admin.ModelAdmin):
    list_display = ('monthly_process', 'freelancer', 'status', 'payment_amount')
    list_filter = ('monthly_process', 'status')

@admin.register(ContactEntity)
class ContactEntityAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'email', 'phone')
    list_filter = ('kind',)

@admin.register(EntityContactPerson)
class EntityContactPersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'corporate_entity', 'email', 'phone')

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'worker_entity', 'project_name', 'upstream_entity', 'downstream_entity')
    list_filter = ('worker_entity', 'upstream_entity')

@admin.register(ServiceContract)
class ServiceContractAdmin(admin.ModelAdmin):
    list_display = ('id', 'assignment', 'unit_price', 'valid_from', 'valid_to')
    list_filter = ('valid_from', 'valid_to')
