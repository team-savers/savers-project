import type { EvacuationStep } from '../pages/EvacuationFlow'

export const speechScripts: Record<EvacuationStep, string> = {
  alert: '관악구에 호우 경보가 발령되었습니다. 상황 확인하기를 눌러 다음 안내를 확인하세요.',
  profile: '맞춤 안내를 위해 나이와 성별을 선택적으로 입력할 수 있습니다. 입력하지 않고 건너뛸 수도 있습니다.',
  choice: '어떻게 도와드릴까요? 도움이 필요해요 또는 혼자서 대피할게요 중 하나를 선택하세요.',
  help: '도움이 필요하다고 표시했습니다. 긴급한 상황이라면 119에 바로 연락하세요.',
  shelter: '즉시 대피 단계입니다. 추천 대피소와 침수 회피 경로 정보를 확인하세요.',
  route: '침수 구간을 피하는 경로를 안내합니다. 지도와 차단 구간 정보를 확인하세요.',
  arrival: '사용자가 도착 완료로 표시했습니다. 공식 재난 안내를 계속 확인하세요.',
}
