/** One workspace composes conditions, messages and canonical server cards. */
import { Workbench } from "@/components/workbench";
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ article?: string | string[] }>;
}) {
  const article = (await searchParams).article;
  return (
    <Workbench articleId={typeof article === "string" ? article : undefined} />
  );
}
