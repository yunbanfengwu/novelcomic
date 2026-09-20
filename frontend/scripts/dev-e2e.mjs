// E2E 验证实例启动器：直接以 node 起 vite（绕开 npm/cmd 包装，preview 工具可直接 spawn），
// 后端指向独立验证后端 127.0.0.1:8766（vite.config 读 NOVELCOMIC_API）。
process.env.NOVELCOMIC_API = process.env.NOVELCOMIC_API || 'http://127.0.0.1:8766'

const { createServer } = await import('vite')
const server = await createServer({ server: { port: 5221, strictPort: true } })
await server.listen()
server.printUrls()
