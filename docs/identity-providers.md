# Identity Provider (IdP) Configuration

JFYI uses OAuth 2.0 / OpenID Connect (OIDC) to authenticate users via external Identity Providers. This ensures JFYI never handles or stores user passwords directly.

This guide provides step-by-step instructions on how to configure the supported identity providers: **GitHub**, **Google**, and **Microsoft Entra ID**.

> **⚠️ Security Warning:** This is a public open-source repository. **Never** commit your actual Client IDs or Client Secrets to version control. Always pass them via environment variables or a secure secret manager (e.g., Kubernetes Secrets, `.env` file excluded by `.gitignore`).

---

## 1. GitHub OAuth App

1. Go to your personal or organization settings on GitHub.
2. Navigate to **Developer settings** > **OAuth Apps** > **New OAuth App**.
3. Fill in the application details:
   - **Application name**: `JFYI Dashboard` (or your preferred name)
   - **Homepage URL**: `https://<your-jfyi-domain>` (e.g., `https://jfyi.k3s.hlan.net`)
   - **Authorization callback URL**: `https://<your-jfyi-domain>/auth/callback/github`
4. Click **Register application**.
5. Copy the **Client ID**.
6. Click **Generate a new client secret** and copy the resulting secret.

**Environment Variables Required:**
```env
JFYI_GITHUB_CLIENT_ID="your_github_client_id"
JFYI_GITHUB_CLIENT_SECRET="your_github_client_secret"
```

---

## 2. Google OAuth 2.0 Client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing one.
3. Navigate to **APIs & Services** > **Credentials**.
4. Click **+ CREATE CREDENTIALS** > **OAuth client ID**.
   - *Note: You may need to configure your OAuth consent screen first if you haven't already.*
5. Select **Web application** as the Application type.
6. Under **Authorized redirect URIs**, add:
   - `https://<your-jfyi-domain>/auth/callback/google`
7. Click **Create**.
8. Copy the **Client ID** and **Client Secret** from the modal.

**Environment Variables Required:**
```env
JFYI_GOOGLE_CLIENT_ID="your_google_client_id"
JFYI_GOOGLE_CLIENT_SECRET="your_google_client_secret"
```

---

## 3. Microsoft Entra ID (formerly Azure AD)

1. Go to the [Azure Portal](https://portal.azure.com/) or [Entra Admin Center](https://entra.microsoft.com/).
2. Navigate to **App registrations** > **New registration**.
3. Fill in the details:
   - **Name**: `JFYI Dashboard`
   - **Supported account types**: Select "Accounts in this organizational directory only" (Single tenant) or "Accounts in any organizational directory" (Multitenant) depending on your needs.
   - **Redirect URI**: Select **Web** and enter `https://<your-jfyi-domain>/auth/callback/entra`
4. Click **Register**.
5. Copy the **Application (client) ID** from the Overview page.
6. Navigate to **Certificates & secrets** > **Client secrets** > **New client secret**.
7. Add a description, set an expiration, and click **Add**.
8. Copy the **Value** of the client secret immediately (it will be hidden later).

**Environment Variables Required:**
```env
JFYI_ENTRA_CLIENT_ID="your_entra_client_id"
JFYI_ENTRA_CLIENT_SECRET="your_entra_client_secret"
# If using a specific tenant (not common multitenant):
# JFYI_ENTRA_TENANT_ID="your_tenant_id"
```

---

## Configuration in Kubernetes / Helm

When deploying to Kubernetes using the Helm chart, inject these secrets via the `env` block in your `values-local.yaml` (which is `.gitignore`d), or ideally, reference a pre-existing Kubernetes Secret.

Example using plain environment variables:

```yaml
env:
  JFYI_JWT_SECRET: "generate_a_long_random_string_here"
  JFYI_GITHUB_CLIENT_ID: "..."
  JFYI_GITHUB_CLIENT_SECRET: "..."
```
