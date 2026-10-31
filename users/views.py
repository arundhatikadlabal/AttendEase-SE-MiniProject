from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as PasswordValidationError
from django.db.models import F
from django.shortcuts import render
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .security import clear_failed_logins, is_login_locked, record_failed_login
from .serializers import RegistrationSerializer
from .services import (
    reset_password,
    send_password_reset_email,
    valid_password_reset_token,
)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"id": user.pk, "name": user.name, "email": user.email, "role": user.role},
            status=status.HTTP_201_CREATED,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = serializers.Serializer(data=request.data)
        serializer.fields["email"] = serializers.EmailField()
        serializer.is_valid(raise_exception=True)
        send_password_reset_email(
            email=serializer.validated_data["email"], request=request
        )
        return Response(
            {"detail": "If the account exists, a reset email has been sent."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        uid = request.query_params.get("uid", "")
        token = request.query_params.get("token", "")
        if not valid_password_reset_token(uid=uid, token=token):
            return Response({"detail": "Invalid or expired reset link."}, status=400)
        return render(
            request, "users/password_reset_confirm.html", {"uid": uid, "token": token}
        )

    def post(self, request):
        serializer = serializers.Serializer(data=request.data)
        serializer.fields["uid"] = serializers.CharField()
        serializer.fields["token"] = serializers.CharField()
        serializer.fields["new_password"] = serializers.CharField()
        serializer.is_valid(raise_exception=True)
        try:
            changed = reset_password(**serializer.validated_data)
        except PasswordValidationError as error:
            return Response({"new_password": error.messages}, status=400)
        if not changed:
            return Response({"detail": "Invalid or expired reset link."}, status=400)
        return Response({"detail": "Password has been reset."})


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        if is_login_locked(email):
            return Response(
                {"detail": "Too many login attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(
            request,
            email=email,
            password=serializer.validated_data["password"],
        )
        if user is None:
            record_failed_login(email)
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        clear_failed_logins(email)
        refresh = RefreshToken.for_user(user)
        refresh["token_version"] = user.token_version
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_token = request.data.get("refresh")
        if not isinstance(raw_token, str):
            return Response(
                {"detail": "Invalid refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            refresh = RefreshToken(raw_token)
        except TokenError:
            return Response(
                {"detail": "Invalid refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user = User.objects.filter(pk=refresh.get("user_id"), is_active=True).first()
        if user is None or refresh.get("token_version") != user.token_version:
            return Response(
                {"detail": "Refresh token has been revoked."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({"access": str(refresh.access_token)})


class LogoutView(APIView):
    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(
            token_version=F("token_version") + 1
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request):
        user = request.user
        return Response(
            {"id": user.pk, "name": user.name, "email": user.email, "role": user.role}
        )
