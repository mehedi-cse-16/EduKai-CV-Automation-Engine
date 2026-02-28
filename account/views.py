from django.conf import settings
from django.contrib.auth import get_user_model

from drf_spectacular.utils import extend_schema, OpenApiResponse

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from account.serializers import (
    CookieTokenRefreshSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserProfileSerializer,
    ProfileUpdateSerializer,
    PasswordUpdateSerializer,
    ForgotPasswordSerializer,
    VerifyOTPSerializer,
    ResetPasswordSerializer,
)

from account.utils.cookies import set_auth_cookies, unset_auth_cookies

User = get_user_model()


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
class RegisterView(APIView):
    """
    POST /api/auth/register/
    Register a new user. Returns user profile + sets auth cookies.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        request=RegisterSerializer,
        responses={
            201: UserProfileSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
        summary="Register a new user",
        tags=["Auth"],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Generate tokens immediately after registration (auto-login)
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response = Response(
            {
                "message": "Registration successful.",
                "user": UserProfileSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )
        set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)
        return response


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginView(APIView):
    """
    POST /api/auth/login/
    Authenticate with email + password. Sets HttpOnly auth cookies.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: UserProfileSerializer,
            401: OpenApiResponse(description="Invalid credentials"),
        },
        summary="Login with email and password",
        tags=["Auth"],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        user = validated["user"]
        access_token = validated["access"]
        refresh_token = validated["refresh"]

        response = Response(
            {
                "message": "Login successful.",
                "user": UserProfileSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )
        set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)
        return response


# ---------------------------------------------------------------------------
# Token Refresh
# ---------------------------------------------------------------------------
class TokenRefreshView(APIView):
    """
    POST /api/auth/token/refresh/
    Reads refresh token from HttpOnly cookie, returns a new access token cookie.
    No body required.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Access token refreshed successfully"),
            401: OpenApiResponse(description="Invalid or expired refresh token"),
        },
        summary="Refresh access token using cookie",
        tags=["Auth"],
    )
    def post(self, request):
        serializer = CookieTokenRefreshSerializer(context={"request": request})

        try:
            data = serializer.validate({})
        except (InvalidToken, TokenError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        response = Response({"message": "Token refreshed successfully."}, status=status.HTTP_200_OK)

        # Always set the new access token cookie
        from django.conf import settings
        response.set_cookie(
            key=settings.SIMPLE_JWT.get("AUTH_COOKIE_ACCESS", "access_token"),
            value=data["access"],
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Lax",
            path="/",
        )

        # If refresh token was rotated, set the new one too
        if "refresh" in data:
            from django.conf import settings as s
            response.set_cookie(
                key=s.SIMPLE_JWT.get("REFRESH_COOKIE_NAME", "refresh_token"),
                value=data["refresh"],
                max_age=int(s.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
                httponly=True,
                secure=not settings.DEBUG,
                samesite="Lax",
                path=s.SIMPLE_JWT.get("REFRESH_COOKIE_PATH", "/api/auth"),
            )

        return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Blacklists the refresh token and clears both auth cookies.
    Requires authentication.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Logout successful"),
            400: OpenApiResponse(description="Invalid or missing refresh token"),
        },
        summary="Logout and invalidate tokens",
        tags=["Auth"],
    )
    def post(self, request):
        from django.conf import settings

        refresh_cookie_name = settings.SIMPLE_JWT.get("REFRESH_COOKIE_NAME", "refresh_token")
        refresh_token = request.COOKIES.get(refresh_cookie_name)

        if not refresh_token:
            return Response(
                {"detail": "Refresh token not found. You may already be logged out."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()  # Invalidate token in DB (requires token_blacklist app)
        except TokenError:
            # Token already invalid/expired — still clear cookies
            pass

        response = Response({"message": "Logout successful."}, status=status.HTTP_200_OK)
        unset_auth_cookies(response)
        return response


# ---------------------------------------------------------------------------
# Profile (Me)
# ---------------------------------------------------------------------------
class MeView(APIView):
    """
    GET /api/auth/me/
    Returns the currently authenticated user's profile.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer},
        summary="Get current user profile",
        tags=["Auth"],
    )
    def get(self, request):
        serializer = UserProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------
# Profile Update
# ---------------------------------------------------
class ProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserProfileSerializer},
        summary="Update current user profile",
        tags=["Auth"],
    )
    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Profile updated successfully.",
                    "data": UserProfileSerializer(request.user, context={"request": request}).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------
# Password Update
# ---------------------------------------------------
class PasswordUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PasswordUpdateSerializer,
        responses={
            200: OpenApiResponse(description="Password updated successfully"),
            400: OpenApiResponse(description="Validation error"),
        },
        summary="Change current user's password",
        tags=["Auth"],
    )

    def post(self, request):
        serializer = PasswordUpdateSerializer(
            data=request.data,
            context={"request": request}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Password updated successfully."},
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------
class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Sends an OTP to the provided email if an account exists.
    Always returns a generic success message (security best practice).
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=ForgotPasswordSerializer,
        responses={
            200: OpenApiResponse(description="OTP sent if account exists"),
            429: OpenApiResponse(description="Rate limit exceeded"),
        },
        summary="Request a password reset OTP",
        tags=["Auth - Password Reset"],
    )
    def post(self, request):
        from account.utils.password_reset import (
            can_request_otp, generate_numeric_otp,
            store_otp_for_email, send_otp_email,
        )

        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        allowed, reason, retry_after, remaining_reqs = can_request_otp(email)
        if not allowed:
            return Response(
                {"detail": reason, "retry_after": retry_after, "remaining_requests": remaining_reqs},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp = generate_numeric_otp()
        store_otp_for_email(email, otp)

        # Only send if the user exists — but don't reveal this to the caller
        if User.objects.filter(email__iexact=email).exists():
            try:
                send_otp_email(email, otp)
            except Exception:
                pass  # Never expose email/SMTP errors to the client

        cooldown = getattr(settings, "PASSWORD_RESET_RESEND_COOLDOWN", 60)
        return Response(
            {
                "detail": "If an account exists for that email, you will receive an OTP shortly.",
                "retry_after": retry_after or cooldown,
                "remaining_requests": remaining_reqs,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Verify OTP
# ---------------------------------------------------------------------------
class VerifyOTPView(APIView):
    """
    POST /api/auth/verify-otp/
    Verifies the OTP. On success, sets a short-lived verified flag in Redis.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=VerifyOTPSerializer,
        responses={
            200: OpenApiResponse(description="OTP verified successfully"),
            400: OpenApiResponse(description="Invalid or expired OTP"),
            403: OpenApiResponse(description="Too many failed attempts"),
        },
        summary="Verify password reset OTP",
        tags=["Auth - Password Reset"],
    )
    def post(self, request):
        from django.conf import settings as django_settings
        from account.utils.password_reset import (
            increment_verify_attempts, verify_otp,
            set_verified_for_email, clear_otp_for_email, clear_verified_for_email,
        )

        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]

        max_attempts = getattr(django_settings, "PASSWORD_RESET_MAX_VERIFY_ATTEMPTS", 5)
        attempts = increment_verify_attempts(email)

        if attempts > max_attempts:
            clear_otp_for_email(email)
            clear_verified_for_email(email)
            return Response(
                {"detail": "Too many incorrect attempts. Please request a new OTP."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not verify_otp(email, otp):
            remaining = max(0, max_attempts - attempts)
            return Response(
                {"detail": "Invalid or expired OTP.", "attempts_remaining": remaining},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # OTP is valid — mark verified and invalidate OTP (prevent reuse)
        set_verified_for_email(email)
        clear_otp_for_email(email)

        return Response(
            {"detail": "OTP verified. You may now reset your password."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Reset Password
# ---------------------------------------------------------------------------
class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Resets the password. Requires prior OTP verification.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        request=ResetPasswordSerializer,
        responses={
            200: OpenApiResponse(description="Password reset successfully"),
            400: OpenApiResponse(description="OTP not verified or validation error"),
        },
        summary="Reset password after OTP verification",
        tags=["Auth - Password Reset"],
    )
    def post(self, request):
        from account.utils.password_reset import (
            is_verified_for_email, clear_verified_for_email, clear_otp_for_email,
        )

        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        new_password = serializer.validated_data["new_password"]

        if not is_verified_for_email(email):
            return Response(
                {"detail": "OTP not verified or session expired. Please verify your OTP first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Clear verified flag and return generic message
            clear_verified_for_email(email)
            return Response(
                {"detail": "Password has been reset successfully."},
                status=status.HTTP_200_OK,
            )

        user.set_password(new_password)
        user.save()

        clear_verified_for_email(email)
        clear_otp_for_email(email)

        return Response(
            {"detail": "Password reset successfully. Please log in with your new password."},
            status=status.HTTP_200_OK,
        )