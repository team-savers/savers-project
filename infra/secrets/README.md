# infra/secrets/

FCM Admin SDK 서비스 계정 JSON을 배포 VM에서 여기 둡니다(ADR-0023).
이 디렉터리 자체는 `docker-compose.yml`의 backend 서비스가 `/run/secrets/fcm`로
항상 마운트합니다 — 파일이 없어도(= `recording` 채널) 무해합니다.

## 사용법

1. 파일명은 `service-account.json`으로 고정합니다(`.gitignore`의
   `service-account*.json` 패턴과 일치시켜, 실수로 커밋되는 걸 한 겹 더 막습니다).
2. **소유권/권한을 맞춥니다.** 컨테이너는 `appuser`(uid 10001)로 돌지만 이 마운트는
   bind mount라 호스트 쪽 소유권을 그대로 가져옵니다. 이 파일은 FCM 발송 권한을 가진
   개인키이므로 다른 사용자도 읽을 수 있게 여는 `chmod 644`는 쓰지 않습니다 — uid를
   컨테이너와 맞추고 소유자만 읽게 잠급니다(ADR-0022가 세션 저장소 평문 예외의
   통제로 삼은 것과 같은 0600 기준):
   ```
   sudo chown 10001:10001 infra/secrets/service-account.json
   sudo chmod 600 infra/secrets/service-account.json
   ```
   권한이 막혀 있으면 `fcm` 채널에서 기동이 "FCM service account file is not readable"로
   즉시 실패합니다(설계 — 조용히 `recording`으로 떨어지지 않습니다).
3. `infra/.env`에서:
   ```
   SAVERS_PUSH_CHANNEL=fcm
   SAVERS_FCM_SERVICE_ACCOUNT_PATH=/run/secrets/fcm/service-account.json
   ```
   `SAVERS_FCM_SERVICE_ACCOUNT_PATH`는 **컨테이너 내부 경로**입니다 — 호스트 경로가 아닙니다.
4. `docker compose ... up -d --build`로 재기동하면 반영됩니다(`restart`로는 안 됩니다 —
   환경변수를 다시 읽지 않습니다).

이 디렉터리 안의 실제 자격증명 파일은 `.gitignore`가 통째로 막으므로 커밋되지 않습니다 —
이 README만 예외입니다.
