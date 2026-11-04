import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowRight, ArrowUpRight, Play } from '@phosphor-icons/react'
import { sceneForHomeVisit, type HomeScene } from './homeScenes'
import { Brand } from './ui'

const reduceMotion = '(prefers-reduced-motion: reduce)'

function HomeBackground({ motion }: { motion: boolean }) {
  const selectedScene = useRef<HomeScene | null>(null)
  const [scene, setScene] = useState<HomeScene | null>(null)
  const [reduced, setReduced] = useState(() => matchMedia(reduceMotion).matches)
  const [videoFailed, setVideoFailed] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const videoActive = motion && !reduced && !videoFailed

  useLayoutEffect(() => {
    selectedScene.current ??= sceneForHomeVisit()
    setScene(selectedScene.current)
  }, [])

  useEffect(() => {
    const preference = matchMedia(reduceMotion)
    const syncPreference = () => setReduced(preference.matches)
    preference.addEventListener('change', syncPreference)
    syncPreference()
    return () => preference.removeEventListener('change', syncPreference)
  }, [])

  useEffect(() => {
    const player = video.current
    if (!player || !scene || !videoActive) return

    let frame: number | undefined
    const stopFading = () => {
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = undefined
    }
    const paintFade = () => {
      const blend = Math.min(player.currentTime / 0.28, (player.duration - player.currentTime) / 0.6)
      const progress = Number.isFinite(blend) ? Math.max(0, Math.min(1, blend)) : 0
      player.style.opacity = String(progress ** 2 * (3 - 2 * progress))
    }
    const tick = () => {
      frame = undefined
      if (document.hidden || player.paused) return
      paintFade()
      frame = requestAnimationFrame(tick)
    }
    const onPlaying = () => {
      if (document.hidden) player.pause()
      else if (!scene.fadeLoop) player.style.opacity = '1'
      else if (frame === undefined) tick()
    }
    const syncPlayback = () => {
      if (document.hidden) {
        stopFading()
        player.pause()
      } else {
        void player.play().catch(() => {})
        if (!player.paused && player.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) onPlaying()
      }
    }

    player.addEventListener('playing', onPlaying)
    if (scene.fadeLoop) {
      player.addEventListener('pause', stopFading)
      player.addEventListener('waiting', stopFading)
      player.addEventListener('seeking', paintFade)
    }
    document.addEventListener('visibilitychange', syncPlayback)
    syncPlayback()
    return () => {
      document.removeEventListener('visibilitychange', syncPlayback)
      player.removeEventListener('playing', onPlaying)
      if (scene.fadeLoop) {
        player.removeEventListener('pause', stopFading)
        player.removeEventListener('waiting', stopFading)
        player.removeEventListener('seeking', paintFade)
      }
      stopFading()
      player.pause()
    }
  }, [videoActive, scene])

  if (!scene) return null

  return <>
    <img className="home-still" src={scene.poster} alt={`图序主题画面：${scene.name}`} fetchPriority="high" />
    {videoActive && <video
      ref={video}
      className="home-film"
      data-scene={scene.id}
      src={scene.video}
      poster={scene.poster}
      muted
      autoPlay
      loop
      playsInline
      preload="auto"
      aria-hidden="true"
      onError={() => setVideoFailed(true)}
    />}
  </>
}

export default function Home({onEnter,onCreate,onResume,motion}:{onEnter:()=>void;onCreate:()=>void;onResume:()=>void;motion:boolean}) {
 return <main className="home">
  <HomeBackground motion={motion}/>
  <div className="home-shade"/><div className="home-grain" aria-hidden="true"/>
  <nav className="home-nav"><Brand/><div><button onClick={onEnter}>创作工作台</button><button onClick={onResume}>我的项目</button><span className="home-badge">开源工作台 1.4</span></div><button className="home-nav-cta" onClick={onCreate}>开始创作 <ArrowUpRight size={18}/></button></nav>
  <section className="home-copy"><div className="home-kicker"><span/> A SPACE FOR YOUR NEXT STORY</div><h1>让故事，<br/>连接<span>脉动。</span></h1><p>从一份素材，到一个值得讲述的故事。<br/>把想象交给 AI，把每一次选择留给你。</p><div className="home-actions"><button onClick={onCreate}>开启一个故事 <ArrowRight size={23}/></button><button onClick={onEnter}><Play size={17} weight="fill"/> 探索工作台</button></div><div className="home-principles"><span>本地素材</span><i/><span>对话剪辑</span><i/><span>自由掌控</span></div></section>
  <div className="home-film-note"><span className="frame-corner"/><div><small>THE OPENING FRAME</small><p>故事，始于看见。</p></div><span className="home-time">00:00:01:12</span></div>
  <footer className="home-footer"><span>素材 <i>／</i> 叙事 <i>／</i> 成片</span><div><span className="status-dot"/> YOUR STORY, YOUR RHYTHM</div><button onClick={onEnter}>进入工作台 <ArrowRight size={16}/></button></footer>
 </main>
}
