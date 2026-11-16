import uuid
from urllib.parse import quote

from django.conf import settings
from django.db import models


class ImageUrlMixin:
    """Photo URL resolution: an admin upload (`image_upload`) wins over the
    legacy static path in `image` (e.g. 'categorized_product/9/9 (023).png')."""

    @property
    def image_url_path(self):
        upload = getattr(self, 'image_upload', None)
        if upload:
            return upload.url
        if self.image:
            return f'{settings.STATIC_URL}{quote(self.image, safe="/")}'
        return ''


class Category(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=10, default='')
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(ImageUrlMixin, models.Model):
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, default='')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, default='per piece')
    image = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Legacy static path under static/, e.g. categorized_product/9/9 (023).png.')
    image_upload = models.ImageField(
        upload_to='marketplace_uploads/', blank=True, null=True,
        help_text='Upload a photo directly. Takes priority over the static path when both are set.')
    in_stock = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_featured', 'name']

    def __str__(self):
        return self.name

    @property
    def category_name(self):
        return self.category.name if self.category else ''

    @property
    def category_icon(self):
        return self.category.icon if self.category else ''


class PharmacyProduct(ImageUrlMixin, models.Model):
    """The pharmacy catalogue - medicines and health products. A separate table from Product on purpose
    (different fields, its own cart and orders). Prices may be 0 for items that are quoted on request."""
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, help_text='Optional free-text grouping, e.g. "Pain relief"')
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='0 = price on request')
    unit = models.CharField(max_length=50, default='per piece')
    image = models.CharField(max_length=200, blank=True, default='', help_text='Legacy static path under static/')
    image_upload = models.ImageField(upload_to='pharmacy_uploads/', blank=True, null=True,
                                     help_text='Upload a photo directly. Takes priority over the static path.')
    in_stock = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    requires_prescription = models.BooleanField(default=False, help_text='Shows an Rx-required badge on the storefront.')
    brand = ''  # same shape as Product for the shared templates
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_featured', 'name']

    def __str__(self):
        return self.name

    @property
    def category_name(self):
        return self.category

    @property
    def category_icon(self):
        return '💊'

    @property
    def price_on_request(self):
        return self.price == 0


class ProductImage(ImageUrlMixin, models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='gallery_images')
    order = models.PositiveSmallIntegerField(default=0)
    image = models.CharField(max_length=200)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.product.name} - image {self.order}'


class ProductVariant(ImageUrlMixin, models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    label = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.CharField(max_length=200, blank=True, default='')
    in_stock = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.product.name} - {self.label}'
