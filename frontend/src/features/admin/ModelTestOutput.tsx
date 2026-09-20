import type { ModelTestResult } from '../../api'

/** 模型测试结果回显（图/音/向量/文本）：模型配置弹框与资源包行内测试共用这一份。 */
export function ModelTestOutput({ result }: { result: ModelTestResult }) {
  if (result.kind === 'image') return <div className="model-test-output"><img src={result.url} alt="模型测试输出" /></div>
  if (result.kind === 'audio') return <div className="model-test-output"><audio controls src={result.url} /></div>
  if (result.kind === 'vector') return <div className="model-test-output">
    <b>向量输出 · {result.dimensions} 维</b>
    {result.endpoint && <div className="dim">调用接口：{result.endpoint}</div>}
    {result.storage_compatible === false && <div className="model-vector-warning">
      测试调用成功，但当前知识库字段为 {result.storage_dimensions} 维，不能直接存储该
      {result.dimensions} 维向量。切换为此模型前需要迁移向量字段并重新生成已有向量。
    </div>}
    <pre>{JSON.stringify(result.vector)}</pre>
  </div>
  return <div className="model-test-output"><b>文本输出</b><div className="model-text-result">{result.text}</div></div>
}
