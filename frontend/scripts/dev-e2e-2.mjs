// E2E 验证实例启动器（第 2 组端口，与其它会话的 8766/5221 组错开）：
// 直接以 node 起 vite，后端指向独立验证后端 127.0.0.1:8767（vite.config 读 NOVELCOMIC_API）。
process.env.NOVELCOMIC_API = process.env.NOVELCOMIC_API || 'http://127.0.0.1:8767'

const { createServer } = await import('vite')
const server = await createServer({ server: { port: 5223, strictPort: true } })
await server.listen()
server.printUrls()
