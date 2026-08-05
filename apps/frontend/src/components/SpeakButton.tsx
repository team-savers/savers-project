// SpeakButton — 브라우저 내장 음성 합성(Web Speech API)으로 메시지 본문을
// 소리 내어 읽어주는 토글 버튼.
//
// 설계 제약:
//   - 외부 음성 합성 API/URL 은 사용하지 않는다. 오직 브라우저 내장
//     window.speechSynthesis 만 사용한다. 네트워크 요청, SDK 로드, API 키
//     가 없어도 동작해야 한다 — 이 경로는 오프라인 폴백의 일부다.
//   - 스크린 리더(TalkBack / VoiceOver / NVDA)가 이미 켜져 있으면 두 음성이
//     섞이지 않도록 주의한다. 스크린 리더 사용자는 본 버튼을 누르지 않아도
//     aria-live 영역을 통해 본문을 들을 수 있으므로, 본 버튼은 시각이
//     있거나 스크린 리더가 꺼진 저시력/인지 장애 사용자를 위한 보조 수단이다.
//
// 접근성 동작:
//   - 활성화 시 버튼 라벨이 `🔊 읽어주기` → `⏹ 멈추기` 로 바뀐다.
//   - speechSynthesis 가 지원되지 않는 환경이면 버튼을 비활성화하고
//     aria-disabled 로 알린다.
//   - 컴포넌트 언마운트 시 진행 중인 음성을 cancel() 로 중단한다.
//     (브라우저 탭을 닫거나 페이지를 떠나도 소리가 멈추도록.)
//   - 같은 버튼을 다시 누르면 진행 중인 음성을 cancel() 하고 새 발화를
//     시작한다 — 중복 재생(두 음성이 겹쳐 들리는 현상)을 막기 위함이다.
//
// 언어 선택:
//   - lang prop 으로 BCP-47 태그(ko-KR / vi-VN)를 받는다. 기본 ko-KR.
//   - speechSynthesis 의 voice 목록에서 lang 접두사가 일치하는 음성을
//     우선 사용한다. 일치 음성이 없으면 브라우저 기본 음성으로 발화한다
//     (사용자 환경에 해당 언어 음성이 설치되어 있지 않은 경우).

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import type { Language } from '../api/types'
import { t } from '../lib/i18n'
import { C } from '../lib/tokens'

interface Props {
  // Text to read aloud.
  text: string
  // UI language for button labels, aria-labels, and speech synthesis voice
  // selection. Defaults to Korean.
  lang?: Language
  // 전체 폭 블록 버튼 여부. 본문 카드 안에서 주 동작 자리에 놓을 때 쓴다.
  // true 면 버튼이 가로 폭을 가득 채우고 틸 채움(주 동작 색)으로 렌더된다.
  // 생략하면 기존 인라인 버튼 형태를 유지한다.
  block?: boolean
}

// 터치 영역 최소 높이(px). EasyText 와 동일 기준.
const MIN_TOUCH_PX = 44

// 브라우저 내장 speechSynthesis 에 대한 최소한의 타입 가드.
// TS 표준 lib 에는 SpeechSynthesis 타입이 있지만, 런타임 가드는 별도로
// 필요하다 — 일부 환경(SSR, 구형 브라우저)에서는 undefined 다.
function getSynth(): SpeechSynthesis | null {
  if (typeof window === 'undefined') return null
  if (typeof window.speechSynthesis === 'undefined') return null
  return window.speechSynthesis
}

// 주어진 lang 접두사에 맞는 음성을 찾는다. 일치하는 음성이 없으면 null.
function pickVoice(
  voices: ReadonlyArray<SpeechSynthesisVoice>,
  lang: string,
): SpeechSynthesisVoice | null {
  // 정확 일치(예: 'ko-KR') → 접두사 일치(예: 'ko') 순으로 찾는다.
  const exact = voices.find((v) => v.lang === lang)
  if (exact !== undefined) return exact
  const prefix = lang.split('-')[0]
  if (prefix !== undefined) {
    const loose = voices.find((v) => v.lang.startsWith(prefix))
    if (loose !== undefined) return loose
  }
  return null
}

export function SpeakButton({ text, lang = 'ko', block = false }: Props): ReactNode {
  // Derive the BCP-47 tag for the speechSynthesis voice selection. The UI
  // labels go through the i18n dictionary; only the synthesis engine needs
  // the BCP-47 form.
  const bcp47 = lang === 'vi' ? 'vi-VN' : 'ko-KR'
  const [speaking, setSpeaking] = useState<boolean>(false)
  // speechSynthesis 지원 여부. 렌더 시 한 번 결정된다.
  const supported = getSynth() !== null

  // 진행 중인 발화를 중단해야 하는지 추적. 컴포넌트 언마운트 시 true 로
  // 설정되어 useEffect cleanup 이 cancel 을 호출한다.
  const cancelledRef = useRef<boolean>(false)

  // 발화 세대 카운터. speechSynthesis.cancel() 은 진행 중이던 utterance 에
  // end 이벤트를 발생시키는데, 그 이벤트가 **새 발화의 start 이후에** 도착할
  // 수 있다. 그러면 옛 utterance 의 onend 가 setSpeaking(false) 로 새 발화의
  // 상태를 덮어써, 실제로 읽고 있는데 speaking 이 false 가 된다. 그 상태에서
  // 본문이 또 바뀌면 아래 "발화 중 텍스트 갱신" 이펙트의 조건이 거짓이 되어
  // 낭독이 조용히 멈춘다 — 단계적 노출에서 "다음"을 발화 중에 누르면 그
  // 다음부터 재발화가 통째로 건너뛰어지는 증상이다(PR #50 리뷰 2라운드).
  // 발화마다 세대 번호를 붙이고, 자기 세대가 아닌 핸들러는 상태를 건드리지
  // 않게 한다.
  const generationRef = useRef<number>(0)

  // 발화 중지. cancel 은 idempotent — 대기열에 없어도 안전하다.
  const stop = useCallback((): void => {
    const synth = getSynth()
    if (synth === null) return
    // 세대를 올려 지금 취소되는 utterance 의 뒤늦은 end/error 가 이후 상태를
    // 건드리지 못하게 한다.
    generationRef.current += 1
    synth.cancel()
    setSpeaking(false)
  }, [])

  // 컴포넌트 언마운트 시 진행 중인 음성 중단.
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      const synth = getSynth()
      if (synth === null) return
      synth.cancel()
    }
  }, [])

  // 페이지가 닫히거나 숨겨질 때에도 음성을 중단(사용자가 다른 앱으로
  // 이동했는데 본 페이지에서 계속 소리가 나는 것을 막기 위함).
  useEffect(() => {
    const onHide = (): void => {
      if (document.hidden) {
        stop()
      }
    }
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
    }
  }, [stop])

  // 새 발화를 시작한다(토글이 아니라 항상 시작) — handleClick과 아래
  // "발화 중 텍스트 갱신" 이펙트가 공유한다.
  const speak = useCallback(
    (toSpeak: string): void => {
      const synth = getSynth()
      if (synth === null) return

      // 새 발화 시작 전에 반드시 잔여 대기열을 비운다. 그렇지 않으면 이전
      // 발화가 누적되어 두 음성이 겹쳐 들린다. 세대를 먼저 올려, 이 cancel
      // 이 유발하는 옛 utterance 의 end 이벤트가 아래 새 핸들러들의 상태를
      // 덮어쓰지 못하게 한다(generationRef 주석 참조).
      const generation = generationRef.current + 1
      generationRef.current = generation
      synth.cancel()
      cancelledRef.current = false

      const utter = new SpeechSynthesisUtterance(toSpeak)
      utter.lang = bcp47
      utter.rate = 0.95
      utter.pitch = 1

      // 해당 언어 음성이 있으면 지정. 없으면 브라우저 기본 음성으로
      // 발화(사용자 환경에 설치된 음성이 없을 수 있다).
      const voices = synth.getVoices()
      const voice = pickVoice(voices, bcp47)
      if (voice !== null) {
        utter.voice = voice
      }

      // 세 핸들러 모두 자기 세대일 때만 상태를 바꾼다 — 더 새로운 발화가
      // 이미 시작됐다면 이 utterance 의 이벤트는 지나간 사건이다.
      utter.onstart = (): void => {
        if (generationRef.current !== generation) return
        if (cancelledRef.current) {
          // 시작되기 전에 이미 취소됨 — 즉시 정지.
          synth.cancel()
          return
        }
        setSpeaking(true)
      }
      utter.onend = (): void => {
        if (generationRef.current !== generation) return
        setSpeaking(false)
      }
      utter.onerror = (): void => {
        if (generationRef.current !== generation) return
        setSpeaking(false)
      }

      synth.speak(utter)
    },
    [bcp47],
  )

  const handleClick = useCallback((): void => {
    // 이미 발화 중이면 토글 → 중지.
    if (speaking) {
      stop()
      return
    }
    speak(text)
  }, [speaking, stop, speak, text])

  // 발화 중에 text prop이 바뀌면(예: EasyText 단계적 노출에서 "다음"을 눌러
  // 문장이 새로 펼쳐짐) 갱신된 문장 전체로 다시 읽는다. 그렇지 않으면
  // 화면에는 새 문장이 보이는데 소리는 이미 끝난 옛 문장에서 멈춰 있는
  // 어긋남이 생긴다 — 이 버튼이 지키려는 "화면과 소리는 같은 문장을
  // 말해야 한다" 불변식이 반대 방향으로 깨진다(PR #50 리뷰). 처음부터
  // 다시 읽으므로 이미 들은 부분이 살짝 반복되지만, 문장이 어긋나는 것보다
  // 낫다는 판단이다.
  const speakingRef = useRef(speaking)
  useEffect(() => {
    speakingRef.current = speaking
  }, [speaking])
  const prevTextRef = useRef(text)
  useEffect(() => {
    if (prevTextRef.current !== text) {
      prevTextRef.current = text
      if (speakingRef.current) {
        speak(text)
      }
    }
  }, [text, speak])

  // 비활성화 스타일: 지원되지 않는 환경에서 버튼이 죽은 컨트롤이 되는
  // 것을 명확히 시각화.
  // block 모드에서는 전체 폭·주 동작 색(틸 채움)으로 렌더한다 — 본문 카드의
  // 주 동작 자리에 놓일 때 쓴다.
  const baseStyle: CSSProperties = block
    ? {
        width: '100%',
        minHeight: '52px',
        padding: '14px 12px',
        fontSize: '16px',
        fontWeight: 700,
        letterSpacing: '-.015em',
        borderRadius: '13px',
        cursor: supported ? 'pointer' : 'not-allowed',
        opacity: supported ? 1 : 0.5,
      }
    : {
        marginTop: '0.5rem',
        minWidth: `${MIN_TOUCH_PX}px`,
        minHeight: `${MIN_TOUCH_PX}px`,
        padding: '0.6rem 0.9rem',
        fontSize: '1rem',
        borderRadius: '8px',
        cursor: supported ? 'pointer' : 'not-allowed',
        opacity: supported ? 1 : 0.5,
      }
  const style: CSSProperties = block
    ? {
        ...baseStyle,
        background: speaking ? C.navy : C.tealText,
        color: C.white,
        border: `2px solid ${speaking ? C.navy : C.tealText}`,
        boxShadow:
          speaking || !supported
            ? 'none'
            : '0 8px 20px -12px rgba(11,110,105,.5)',
      }
    : {
        ...baseStyle,
        background: speaking ? C.tealText : C.white,
        color: speaking ? C.white : C.tealText,
        border: `2px solid ${C.tealText}`,
      }

  return (
    <button
      type="button"
      onClick={handleClick}
      // 지원되지 않는 환경에서는 disabled 로 렌더 — 스크린 리더가 "사용할
      // 수 없음"으로 읽어준다.
      disabled={!supported}
      aria-pressed={speaking}
      aria-disabled={!supported}
      aria-label={
        speaking
          ? t('speak.aria.stop', lang)
          : t('speak.aria.read', lang)
      }
      style={style}
    >
      {speaking ? t('speak.stop', lang) : t('speak.read', lang)}
    </button>
  )
}
