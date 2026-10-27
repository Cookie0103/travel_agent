/** Dynamic guide identity comes from Next; content is read from the validated catalog. */
import { Articles } from "@/components/articles";
export default async function Guide({
  params,
}: {
  params: Promise<{ articleId: string }>;
}) {
  const { articleId } = await params;
  let id = articleId;
  try {
    // 当前 Next 路由参数仍保留百分号编码；只在此边界解码一次。
    id = decodeURIComponent(articleId);
  } catch (error) {
    // 非法转义保留原 ID，由目录查询返回不存在。
    if (!(error instanceof URIError)) throw error;
  }
  return <Articles articleId={id} />;
}
