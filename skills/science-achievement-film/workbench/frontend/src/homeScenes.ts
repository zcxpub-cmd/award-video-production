// The source and hashes of these local assets are recorded in assets/wall/cover-manifest.json.
export type HomeScene = Readonly<{
  id: string
  name: string
  poster: string
  video: string
  fadeLoop?: boolean
}>

export const homeScenes: readonly HomeScene[] = [
  { id: 'blackhole', name: '黑洞', poster: '/cover/blackhole.webp', video: '/cover/blackhole.mp4' },
  { id: 'fold', name: '折光', poster: '/cover/fold.webp', video: '/cover/fold.mp4' },
  { id: 'stellar', name: '星际', poster: '/cover/stellar.webp', video: '/cover/stellar.mp4' },
  { id: 'city', name: '城市', poster: '/cover/city.webp', video: '/cover/city.mp4' },
  { id: 'field', name: '田野', poster: '/cover/field.webp', video: '/cover/field.mp4' },
  { id: 'mountain', name: '高山', poster: '/cover/mountain.webp', video: '/cover/mountain.mp4' },
  { id: 'ocean', name: '大海', poster: '/cover/ocean.webp', video: '/cover/ocean.mp4' },
  { id: 'dna', name: 'DNA', poster: '/cover/dna.webp', video: '/cover/dna.mp4' },
  { id: 'market', name: '市井', poster: '/cover/market.webp', video: '/cover/market.mp4', fadeLoop: true },
  { id: 'village', name: '村庄', poster: '/cover/village.webp', video: '/cover/village.mp4', fadeLoop: true },
  { id: 'forest', name: '森林', poster: '/cover/forest.webp', video: '/cover/forest.mp4', fadeLoop: true },
  { id: 'lake', name: '湖泊', poster: '/cover/lake.webp', video: '/cover/lake.mp4', fadeLoop: true },
  { id: 'desert', name: '沙漠', poster: '/cover/desert.webp', video: '/cover/desert.mp4', fadeLoop: true },
  { id: 'rice', name: '金秋稻田', poster: '/cover/rice.webp', video: '/cover/rice.mp4', fadeLoop: true },
  { id: 'milkyway', name: '仰望星空（银河）', poster: '/cover/milkyway.webp', video: '/cover/milkyway.mp4', fadeLoop: true },
  { id: 'cells', name: '生物细胞', poster: '/cover/cells.webp', video: '/cover/cells.mp4', fadeLoop: true },
  { id: 'molecules', name: '微观分子（水分子）', poster: '/cover/molecules.webp', video: '/cover/molecules.mp4', fadeLoop: true },
  { id: 'garden', name: '晨光花园', poster: '/cover/garden.webp', video: '/cover/garden.mp4', fadeLoop: true },
]

const storageKey = 'yingxu.home-scene-order.v1'
const scenesById = new Map<string, HomeScene>(homeScenes.map(scene => [scene.id, scene]))
type VisitDeck = { remaining: string[]; last: string | null }
let deck: VisitDeck = { remaining: [], last: null }
let storageWritable = true

function isSceneId(id: unknown): id is string {
  return typeof id === 'string' && scenesById.has(id)
}

function readDeck(): VisitDeck {
  if (!storageWritable) return deck
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    // The old rotating queue put the last displayed scene at the end.
    const lastId: unknown = Array.isArray(saved) ? saved.at(-1) : saved?.last
    const last = isSceneId(lastId) ? lastId : null
    const remaining: unknown = saved?.remaining
    if (last && Array.isArray(remaining) && remaining.length < homeScenes.length &&
        remaining.every(id => isSceneId(id) && id !== last) && new Set(remaining).size === remaining.length) {
      return { remaining, last }
    }
    return { remaining: [], last: last ?? deck.last }
  } catch {
    return deck
  }
}

export function sceneForHomeVisit(): HomeScene {
  const { remaining, last } = readDeck()
  if (!remaining.length) {
    remaining.push(...homeScenes.map(scene => scene.id))
    for (let i = remaining.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      const next = remaining[j]
      remaining[j] = remaining[i]
      remaining[i] = next
    }
    if (remaining[0] === last) {
      const j = 1 + Math.floor(Math.random() * (remaining.length - 1))
      const next = remaining[j]
      remaining[j] = remaining[0]
      remaining[0] = next
    }
  }

  const [id, ...rest] = remaining
  deck = { remaining: rest, last: id }
  if (storageWritable) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(deck))
    } catch {
      storageWritable = false
    }
  }

  return scenesById.get(id) ?? homeScenes[0]
}
