import type { VideoInfo } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import VideoView from "./view";

export default async function VideoPage({ params, searchParams }: PageProps<"/videos/[id]">) {
  const { id } = await params;
  const { tab } = await searchParams;
  const { data, status } = await serverApi<VideoInfo>(`videos/${encodeURIComponent(id)}`);
  return (
    <VideoView
      key={id}
      id={id}
      initial={data}
      apiDown={status === 0 || status >= 500}
      initialTab={typeof tab === "string" ? tab : undefined}
    />
  );
}
