# refresh_google_token.py
# Обновляет OAuth-токен Google, если он истёк.
# Запуск: python3 refresh_google_token.py

from google_auth_oauthlib.flow import InstalledAppFlow

from config import load_settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main():
    settings = load_settings(require_bot_token=False)

    print("Открываю браузер для авторизации...")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(settings.oauth_client_secret_file), SCOPES
    )
    creds = flow.run_local_server(port=0)

    settings.oauth_token_file.write_text(creds.to_json(), encoding="utf-8")
    print("Готово! Токен обновлён — можно создавать мастерские.")


if __name__ == "__main__":
    main()
