from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User
from .services import register_user


class RegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    role = serializers.ChoiceField(
        choices=[User.Role.STUDENT, User.Role.FACULTY]
    )

    def create(self, validated_data):
        return register_user(**validated_data)
