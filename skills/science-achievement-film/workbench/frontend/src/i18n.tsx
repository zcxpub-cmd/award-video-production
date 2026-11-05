import { useEffect, useSyncExternalStore } from 'react'
import english from './messages.en.json'

export type Language = 'zh-CN' | 'en'
const storageKey = 'yingxu.language'
const listeners = new Set<() => void>()
const messages: Readonly<Record<string, string>> = english

function initialLanguage(): Language {
  try {
    return localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh-CN'
  } catch {
    return 'zh-CN'
  }
}

let language = initialLanguage()
export const getLanguage = () => language

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function tr(source: string, ...values: unknown[]) {
  const message = language === 'en' && Object.hasOwn(messages, source) ? messages[source] : source
  return message.replace(/\{(\d+)\}/g, (match, index) =>
    Number(index) < values.length ? String(values[index]) : match,
  )
}

// Persisted tasks from either language may contain older server progress strings.
export function taskMessage(source: string) {
  const observation = /^观察素材 (\d+)\/(\d+)$/.exec(source)
  if (observation) return tr('观察素材 {0}/{1}', observation[1], observation[2])
  const provider = /^服务商生成中 · (.+)$/.exec(source)
  if (provider) return tr('服务商生成中 · {0}', provider[1])
  const failure = /^内部处理失败（(.+)），没有伪造输出。$/.exec(source)
  if (failure) return tr('内部处理失败（{0}），没有伪造输出。', failure[1])
  return tr(source)
}

export function useLanguage() {
  const current = useSyncExternalStore(subscribe, getLanguage)
  useEffect(() => {
    document.documentElement.lang = current
    document.title = tr('影序 · 让故事，连接脉动。')
  }, [current])
  return current
}

export function LanguageSwitch() {
  const current = useSyncExternalStore(subscribe, getLanguage)
  const next = current === 'en' ? 'zh-CN' : 'en'
  const label = next === 'en' ? 'Switch to English' : '切换到中文'
  return <button type="button" className="language-switch" lang={next} aria-label={label} title={label} onClick={() => {
    language = next
    try { localStorage.setItem(storageKey, next) } catch { /* The current tab still switches. */ }
    listeners.forEach(listener => listener())
  }}>{next === 'en' ? 'EN' : '中文'}</button>
}
