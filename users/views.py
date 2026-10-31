from django.contrib.auth import authenticate
from django.db.models import F
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .security import clear_failed_logins, is_login_locked, record_failed_login
from .serializers import RegistrationSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "id": user.pk,
                "name": user.name,
                "email": user.email,
                "usn": user.usn,
                "role": user.role,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


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
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            refresh = RefreshToken(raw_token)
        except TokenError:
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        user = User.objects.filter(pk=refresh.get("user_id"), is_active=True).first()
        if user is None or refresh.get("token_version") != user.token_version:
            return Response({"detail": "Refresh token has been revoked."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({"access": str(refresh.access_token)})


class LogoutView(APIView):
    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(token_version=F("token_version") + 1)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    allowed_roles = (User.Role.STUDENT, User.Role.FACULTY, User.Role.ADMIN)

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.pk,
                "name": user.name,
                "email": user.email,
                "usn": user.usn,
                "role": user.role,
            }
        )
