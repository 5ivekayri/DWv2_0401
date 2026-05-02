import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import CustomTokenSerializer, UserRegisterSerializer

log = logging.getLogger("access.api")


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=UserRegisterSerializer, responses={201: UserRegisterSerializer})
    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log.info("signup_succeeded user_id=%s username=%s", user.pk, user.username)
        return Response({"id": user.pk, "username": user.username, "email": user.email}, status=status.HTTP_201_CREATED)


@extend_schema(request=CustomTokenSerializer)
class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        identifier = str(request.data.get("identifier") or request.data.get("username") or "").strip()
        log.info("login_attempt_finished identifier=%s status=%s", identifier, response.status_code)
        return response
