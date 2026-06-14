#!/usr/bin/env bash
#
# tdd-guard.sh — 구현 파일을 수정/생성하려는데 대응 테스트가 없으면 차단한다.
# kestrel 모노레포용: Python(api/, engine/, packages/)과 TypeScript(frontend/) 모두 커버.
#
# Claude Code PreToolUse 훅으로 등록한다 (.claude/settings.json 참고).
# 동작 규약:
#   - stdin 으로 도구 호출 JSON 을 받는다: { "tool_name": ..., "tool_input": { "file_path": ... } }
#   - exit 0  → 허용
#   - exit 2  → 차단 (stderr 메시지가 Claude 에게 전달됨)
#
# 설계 방침: 애매하면 통과(fail-open). "명백히 구현 파일인데 테스트가 없다"일 때만 막는다.
# 가드가 정상 작업을 자꾸 막으면 사람이 가드를 꺼버리기 때문.

set -euo pipefail

# --- 1. stdin JSON 파싱 (python3 사용 — 프로젝트가 어차피 Python을 쓴다) ---
INPUT="$(cat)"

read -r TOOL_NAME FILE_PATH <<EOF
$(python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read() or "{}")
except Exception:
    print(" ")  # 파싱 실패 → 빈 값 → 아래에서 통과
    sys.exit(0)
ti = d.get("tool_input", {}) or {}
name = d.get("tool_name", "") or ""
# Edit/Write/MultiEdit 계열은 file_path, 그 외 형태도 방어적으로
path = ti.get("file_path") or ti.get("path") or ""
print(name, path)
' <<<"$INPUT" 2>/dev/null || echo " ")
EOF

# --- 2. 파일 수정 도구가 아니면 통과 ---
case "$TOOL_NAME" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# 경로가 비었으면 통과
[ -z "${FILE_PATH:-}" ] && exit 0

BASENAME="$(basename "$FILE_PATH")"
DIRNAME="$(dirname "$FILE_PATH")"

# --- 3. 테스트 파일 자체를 만드는 중이면 통과 (테스트 먼저 작성을 허용해야 한다) ---
case "$BASENAME" in
  test_*.py|*_test.py) exit 0 ;;
  *.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx) exit 0 ;;
esac
case "$FILE_PATH" in
  */tests/*|*/__tests__/*|*/test/*) exit 0 ;;
esac

# --- 4. TDD 대상이 아닌 파일은 통과 ---
# 구현 언어 파일이 아니면 통과
case "$BASENAME" in
  *.py|*.ts|*.tsx) ;;
  *) exit 0 ;;
esac

# 테스트가 의미 없는 보일러플레이트/설정/엔트리포인트는 예외
case "$BASENAME" in
  __init__.py|conftest.py|setup.py|main.py|__main__.py) exit 0 ;;
  next.config.ts|tailwind.config.ts|*.config.ts|*.config.tsx) exit 0 ;;
  layout.tsx|page.tsx|loading.tsx|error.tsx|not-found.tsx|route.ts|middleware.ts) exit 0 ;;
  *.d.ts) exit 0 ;;
esac

# 타입 전용 디렉토리(types/)나 마이그레이션 등은 통과
case "$FILE_PATH" in
  */types/*|*/migrations/*|*/.next/*|*/node_modules/*) exit 0 ;;
esac

# --- 5. 대응 테스트 탐색 ---
STEM="${BASENAME%.*}"   # 확장자 제거
EXT="${BASENAME##*.}"

found=0
case "$EXT" in
  py)
    # Python: 같은 디렉토리 / tests 하위 / 프로젝트 tests 어디든
    CANDIDATES=(
      "$DIRNAME/test_${STEM}.py"
      "$DIRNAME/${STEM}_test.py"
      "$DIRNAME/tests/test_${STEM}.py"
    )
    for c in "${CANDIDATES[@]}"; do
      [ -f "$c" ] && found=1 && break
    done
    # 프로젝트 전역에서 test_<stem>.py 탐색 (fallback)
    if [ "$found" -eq 0 ]; then
      if find . -type f \( -name "test_${STEM}.py" -o -name "${STEM}_test.py" \) \
           -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | grep -q .; then
        found=1
      fi
    fi
    ;;
  ts|tsx)
    # TypeScript: 같은 디렉토리 / __tests__ 하위
    CANDIDATES=(
      "$DIRNAME/${STEM}.test.${EXT}"
      "$DIRNAME/${STEM}.spec.${EXT}"
      "$DIRNAME/__tests__/${STEM}.test.${EXT}"
      "$DIRNAME/__tests__/${STEM}.test.tsx"
      "$DIRNAME/__tests__/${STEM}.test.ts"
    )
    for c in "${CANDIDATES[@]}"; do
      [ -f "$c" ] && found=1 && break
    done
    if [ "$found" -eq 0 ]; then
      if find . -type f \( -name "${STEM}.test.ts" -o -name "${STEM}.test.tsx" \
           -o -name "${STEM}.spec.ts" -o -name "${STEM}.spec.tsx" \) \
           -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | grep -q .; then
        found=1
      fi
    fi
    ;;
esac

# --- 6. 테스트가 있으면 통과, 없으면 차단 ---
if [ "$found" -eq 1 ]; then
  exit 0
fi

if [ "$EXT" = "py" ]; then
  EXAMPLE="$DIRNAME/test_${STEM}.py"
else
  EXAMPLE="$DIRNAME/${STEM}.test.${EXT}"
fi

cat >&2 <<MSG
[TDD Guard] '$FILE_PATH' 구현을 수정하려 하지만 대응 테스트가 없습니다.

CLAUDE.md 규칙: 새 기능은 테스트를 먼저 작성하고, 그 테스트를 통과시키는 구현을 작성하세요 (TDD).

먼저 이 테스트를 작성하세요:
  $EXAMPLE

테스트가 정말 불필요한 파일(엔트리포인트·설정 등)이라면 tdd-guard.sh 예외 목록에 추가하세요.
MSG
exit 2
