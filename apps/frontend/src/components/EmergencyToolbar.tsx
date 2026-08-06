// Floating 비상 도구 — 손전등 / 경보음 / 위치 공유. 항상 같은 자리(화면
// 우측)에 라벨과 함께 떠 있어서, 메뉴를 뒤지거나 이런 기능이 있다는 걸
// 미리 기억하고 있지 않아도 눌러서 바로 쓸 수 있게 한다. 아이콘만으로는
// 당황한 상태에서 못 알아볼 수 있어 글자 라벨을 항상 함께 보여준다.
//
// ⚠️ 사이렌 상태는 이 컴포넌트가 소유하지 않는다 — 프롭(sirenOn·onToggleSiren)
// 으로 받는다. 도움 요청 화면에서는 툴바가 렌더되지 않는데(119 버튼 겹침,
// Preview.tsx showToolbar 주석), 사이렌을 여기서 소유하면 그 화면으로 넘어가는
// 순간 언마운트 클린업이 소리를 조용히 꺼버린다 — 도움을 청하는 순간에
// 경보음이 끊기는 것은 겹침만큼이나 나쁜 실패다(PR #54 리뷰 2라운드). 소리의
// 수명은 화면 단계가 아니라 플로우 전체(Preview)에 묶인다. 손전등·위치공유는
// 순간 동작이라 화면이 바뀌면 꺼져도 자연스러우므로 계속 여기서 소유한다.
import { useState } from 'react'
import type { Shelter } from '../api/types'
import { shareShelterInfo } from '../lib/emergencyTools'
import { C, SHADOW_CARD } from '../lib/tokens'

// 위치 공유 버튼 라벨. 룩업으로 두는 이유는 상태가 4개(공유·복사·실패·평상)
// 라 인라인 삼항으로 쓰면 4단 중첩이 되어 읽기 어렵기 때문이다(PR #54 리뷰).
const SHARE_LABELS: Record<'shared' | 'copied' | 'unavailable', string> = {
  shared: '공유됨',
  copied: '복사됨',
  unavailable: '실패',
}
const SHARE_LABEL_IDLE = '위치공유'

export function EmergencyToolbar({
  nearest,
  sirenOn,
  onToggleSiren,
}: {
  nearest: Shelter | null
  sirenOn: boolean
  onToggleSiren: () => void
}) {
  const [flashlightOn, setFlashlightOn] = useState(false)
  const [shareStatus, setShareStatus] = useState<'shared' | 'copied' | 'unavailable' | null>(null)

  async function handleShare() {
    const result = await shareShelterInfo(nearest)
    if (result === 'cancelled') return
    setShareStatus(result)
    window.setTimeout(() => setShareStatus(null), 2500)
  }

  return (
    <>
      {flashlightOn && (
        <button
          type="button"
          onClick={() => setFlashlightOn(false)}
          style={{
            position: 'fixed',
            inset: 0,
            width: '100%',
            height: '100%',
            zIndex: 60,
            background: '#FFFFFF',
            border: 'none',
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
            paddingBottom: '48px',
            cursor: 'pointer',
          }}
        >
          <span style={{ fontSize: '15px', fontWeight: 700, color: C.tertiary }}>화면을 탭하면 꺼집니다</span>
        </button>
      )}

      <div
        style={{
          position: 'fixed',
          right: '12px',
          // 헤더/배너 높이가 화면마다 달라서(56~110px) 가장 큰 경우 기준으로
          // 여유 있게 고정 — 화면 중앙에 두면 세로 중앙 정렬된 버튼들과
          // 겹치므로 상단에 붙인다.
          top: '128px',
          zIndex: 40,
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        <ToolButton icon="🔦" label="손전등" active={flashlightOn} onClick={() => setFlashlightOn(true)} />
        <ToolButton icon="🔊" label={sirenOn ? '소리끄기' : '경보음'} active={sirenOn} onClick={onToggleSiren} />
        <ToolButton
          icon="📍"
          label={shareStatus === null ? SHARE_LABEL_IDLE : SHARE_LABELS[shareStatus]}
          onClick={() => void handleShare()}
        />
      </div>
    </>
  )
}

function ToolButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: string
  label: string
  active?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: '60px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '2px',
        padding: '8px 4px',
        fontFamily: 'inherit',
        background: active === true ? C.hazardInk : 'rgba(255,255,255,.94)',
        color: active === true ? C.hazard : C.navy,
        border: `1px solid ${C.border}`,
        borderRadius: '14px',
        boxShadow: SHADOW_CARD,
        cursor: 'pointer',
      }}
    >
      <span style={{ fontSize: '19px', lineHeight: 1 }}>{icon}</span>
      <span style={{ fontSize: '10.5px', fontWeight: 700, whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}
