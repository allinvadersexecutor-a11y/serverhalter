const http = require('http')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const PORT = parseInt(process.env.BOT_PORT || '9001')
let bot = null
let seq = 0
let ended = null
const msgs = []

function push(kind, text) {
  seq += 1
  msgs.push({ n: seq, kind, text })
  if (msgs.length > 500) msgs.shift()
}

function plain(v) {
  return JSON.parse(JSON.stringify(v, (k, x) => (typeof x === 'bigint' ? Number(x) : x)))
}

function comps(it) {
  try {
    return plain(it.components !== undefined ? it.components : it.nbt !== undefined ? it.nbt : null)
  } catch (e) {
    return String(e)
  }
}

function itemInfo(it) {
  if (!it) return null
  let c = comps(it)
  const s = JSON.stringify(c)
  if (s && s.length > 2500) c = s.slice(0, 2500) + '...'
  return { slot: it.slot, name: it.name, count: it.count, display: it.displayName, components: c }
}

function pickEntity(a) {
  if (a.id !== undefined) return bot.entities[a.id]
  const here = bot.entity.position
  const list = Object.values(bot.entities)
    .filter((e) => e !== bot.entity && (!a.type || e.name === a.type || e.type === a.type))
    .sort((p, q) => p.position.distanceTo(here) - q.position.distanceTo(here))
  return list[0]
}

function vec(a) {
  return new Vec3(a.x, a.y, a.z)
}

async function sneaking(a, fn) {
  if (a.sneak) bot.setControlState('sneak', true)
  try {
    return await fn()
  } finally {
    bot.setControlState('sneak', false)
  }
}

const ops = {
  connect(a) {
    return new Promise((resolve, reject) => {
      if (bot) {
        try {
          bot.quit()
        } catch (e) {}
        bot = null
      }
      ended = null
      const b = mineflayer.createBot({
        host: a.host || '127.0.0.1',
        port: a.port || 25565,
        username: a.username || 'ChemBot',
        version: a.version || '1.21.6',
        auth: 'offline'
      })
      bot = b
      let done = false
      b.on('message', (m, pos) => push(pos, m.toString()))
      b.on('kicked', (r) => {
        ended = 'kicked: ' + JSON.stringify(r)
        push('kicked', ended)
        if (!done) {
          done = true
          reject(new Error(ended))
        }
      })
      b.on('end', (r) => {
        ended = 'end: ' + r
        push('end', ended)
        if (!done) {
          done = true
          reject(new Error(ended))
        }
      })
      b.on('error', (e) => {
        push('error', String(e))
        if (!done) {
          done = true
          reject(e)
        }
      })
      b.once('spawn', () => {
        done = true
        resolve({ spawned: true, position: plain(b.entity.position), username: b.username })
      })
      setTimeout(() => {
        if (!done) {
          done = true
          reject(new Error('sin spawn en 40 s'))
        }
      }, 40000)
    })
  },
  async state() {
    return plain({
      position: bot.entity.position,
      yaw: bot.entity.yaw,
      pitch: bot.entity.pitch,
      health: bot.health,
      food: bot.food,
      gameMode: bot.game.gameMode,
      dimension: bot.game.dimension,
      held: itemInfo(bot.heldItem),
      hotbarSlot: bot.quickBarSlot,
      ended
    })
  },
  async inventory() {
    return bot.inventory.slots.map(itemInfo).filter(Boolean)
  },
  async chat(a) {
    bot.chat(a.text)
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { sent: a.text }
  },
  async hotbar(a) {
    if (a.name || a.match) {
      const it = bot.inventory.items().find((i) => {
        if (a.name && i.name !== a.name && i.displayName !== a.name) return false
        if (a.match && !JSON.stringify(comps(i)).includes(a.match)) return false
        return true
      })
      if (!it) throw new Error('no hay ese ítem en el inventario')
      await bot.equip(it, 'hand')
    } else {
      bot.setQuickBarSlot(a.slot)
      await bot.waitForTicks(2)
    }
    return itemInfo(bot.heldItem)
  },
  async use_item(a) {
    await sneaking(a, async () => {
      bot.activateItem(!!a.offhand)
      await bot.waitForTicks(a.ticks !== undefined ? a.ticks : 3)
      bot.deactivateItem()
    })
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { held: itemInfo(bot.heldItem) }
  },
  async use_block(a) {
    const b = bot.blockAt(vec(a))
    if (!b) throw new Error('bloque no cargado')
    await sneaking(a, () => bot.activateBlock(b))
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { block: b.name, held: itemInfo(bot.heldItem) }
  },
  async use_entity(a) {
    const e = pickEntity(a)
    if (!e) throw new Error('entidad no encontrada')
    await sneaking(a, () => bot.activateEntity(e))
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { entity: e.name, id: e.id, held: itemInfo(bot.heldItem) }
  },
  async attack(a) {
    const e = pickEntity(a)
    if (!e) throw new Error('entidad no encontrada')
    bot.attack(e)
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { entity: e.name, id: e.id }
  },
  async entities(a) {
    const here = bot.entity.position
    return Object.values(bot.entities)
      .filter((e) => e !== bot.entity)
      .map((e) => ({ id: e.id, name: e.name, type: e.type, position: plain(e.position), distance: +e.position.distanceTo(here).toFixed(2) }))
      .sort((p, q) => p.distance - q.distance)
      .slice(0, a.max || 15)
  },
  async place(a) {
    const ref = bot.blockAt(vec(a))
    if (!ref) throw new Error('bloque de referencia no cargado')
    await bot.placeBlock(ref, new Vec3(a.fx || 0, a.fy !== undefined ? a.fy : 1, a.fz || 0))
    await bot.waitForTicks(a.wait !== undefined ? a.wait : 10)
    return { placedOn: ref.name }
  },
  async dig(a) {
    const b = bot.blockAt(vec(a))
    if (!b) throw new Error('bloque no cargado')
    await bot.dig(b)
    return { dug: b.name }
  },
  async look(a) {
    await bot.lookAt(vec(a), true)
    return { yaw: bot.entity.yaw, pitch: bot.entity.pitch }
  },
  async messages(a) {
    const since = a.since || 0
    return { seq, messages: msgs.filter((m) => m.n > since) }
  },
  async wait(a) {
    await bot.waitForTicks(a.ticks)
    return { waited: a.ticks }
  },
  async disconnect() {
    bot.quit()
    bot = null
    return { bye: true }
  }
}

function send(res, obj) {
  const body = JSON.stringify(obj, (k, x) => (typeof x === 'bigint' ? Number(x) : x))
  res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) })
  res.end(body)
}

http
  .createServer((req, res) => {
    if (req.url === '/health') return send(res, { ok: true, connected: !!bot, ended })
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', async () => {
      const s0 = seq
      try {
        const j = JSON.parse(body || '{}')
        const f = ops[j.op]
        if (!f) throw new Error('operación desconocida: ' + j.op)
        if (j.op !== 'connect' && !bot) throw new Error('bot no conectado: usa bot_connect')
        const result = await f(j.args || {})
        send(res, { ok: true, result, messages: msgs.filter((m) => m.n > s0), seq })
      } catch (e) {
        send(res, { ok: false, error: String((e && e.message) || e), messages: msgs.filter((m) => m.n > s0) })
      }
    })
  })
  .listen(PORT, '127.0.0.1')
