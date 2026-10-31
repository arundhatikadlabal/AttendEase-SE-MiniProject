from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError
from rest_framework import serializers

from .models import User
from .services import register_user


class RegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    usn = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    password = serializers.CharField(write_only=True, validators=[validate_password])
    role = serializers.ChoiceField(
        choices=[User.Role.STUDENT, User.Role.FACULTY]
    )

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def create(self, validated_data):
        try:
            return register_user(**validated_data)
        except IntegrityError as error:
            raise serializers.ValidationError(
                {"email": "An account with this email already exists."}
            ) from error
