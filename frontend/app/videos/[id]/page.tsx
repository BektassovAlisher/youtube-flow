import type { VideoInfo } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import VideoView from "./view";

export default async function VideoPage({ params }: PageProps<"/videos/[id]">) {
  const { id } = await params;
  return <VideoView id={id} video={await serverApi<VideoInfo>(`videos/${encodeURIComponent(id)}`)} />;
}
