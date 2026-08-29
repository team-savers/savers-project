# infra/secrets/

FCM Admin SDK 서비스 계정 JSON을 배포 VM에서 여기 둡니다(ADR-0023).
이 디렉터리 자체는 `docker-compose.yml`의 backend 서비스가 `/run/secrets/fcm`로
항상 마운트합니다 — 파일이 없어도(= `recording` 채널) 무해합니다.

## 사용법

1. 파일명은 `service-account.json`으로 고정합니다(`.gitignore`의
   `service-account*.json` 패턴과 일치시켜, 실수로 커밋되는 걸 한 겹 더 막습니다).
2. `infra/.env`에서:
   ```
   SAVERS_PUSH_CHANNEL=fcm
   SAVERS_FCM_SERVICE_ACCOUNT_PATH=/run/secrets/fcm/service-account.json
   ```
   `SAVERS_FCM_SERVICE_ACCOUNT_PATH`는 **컨테이너 내부 경로**입니다 — 호스트 경로가 아닙니다.
3. `docker compose ... up -d --build`로 재기동하면 반영됩니다(`restart`로는 안 됩니다 —
   환경변수를 다시 읽지 않습니다).

이 디렉터리 안의 실제 자격증명 파일은 `.gitignore`가 통째로 막으므로 커밋되지 않습니다 —
이 README만 예외입니다.
