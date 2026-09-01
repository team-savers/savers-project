# 백엔드 단독 이미지 — 재난 수집·매칭·발송 오케스트레이션.
# 빌드 컨텍스트는 이 디렉토리(apps/backend)입니다. ai-engine 소스를 참조하지 마세요 —
# 두 앱의 결합은 HTTP 계약뿐이고(AGENTS.md), 이미지에 상대 앱을 넣는 순간 그 성질이 깨집니다.
#   docker build -t savers-backend:dev apps/backend
#   docker run --rm -p 8000:8000 --env-file infra/.env savers-backend:dev
#
# ⚠️ CPU 전용입니다 (ADR-0003). 단일 VM에 backend·ai-engine이 함께 올라갑니다.
FROM python:3.12-slim

# 파이썬 런타임 위생: .pyc 미생성, 로그 버퍼링 해제(컨테이너 로그 지연 방지)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어를 소스와 분리해 캐시 적중률을 높인다.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[fcm]"

# 비루트 실행 — 단일 VM에 여러 서비스가 뜨므로 권한 격리를 유지한다.
RUN useradd --create-home --uid 10001 appuser
# SessionStore SQLite가 얹히는 named volume(infra/docker-compose.yml의 savers_sessions)의
# 마운트 지점을 이미지 안에 미리 appuser 소유로 만들어 둔다. 이 디렉터리가 이미지에 없으면
# Docker가 첫 마운트 시 root:root로 생성해, non-root 컨테이너가 SQLite 파일을 못 열게 된다
# (sqlite3.OperationalError: unable to open database file).
RUN mkdir -p /home/appuser/.savers && chown -R appuser:appuser /home/appuser/.savers
USER appuser

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
