from django.contrib import admin

from .models import Category, PharmacyProduct, Product, ProductImage, ProductVariant


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'in_stock', 'is_featured')
    list_filter = ('category', 'in_stock', 'is_featured')
    search_fields = ('name', 'brand')
    inlines = [ProductImageInline, ProductVariantInline]


@admin.register(PharmacyProduct)
class PharmacyProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'in_stock', 'requires_prescription', 'is_featured')
    list_filter = ('in_stock', 'requires_prescription', 'is_featured')
    search_fields = ('name', 'category')


admin.site.register(Category)
