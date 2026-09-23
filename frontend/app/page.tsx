import type { VideoListItem } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import Home from "./home";

export default async function HomePage() {
  const videos = await serverApi<VideoListItem[]>("videos");
  return <Home examples={videos?.slice(0, 3) ?? []} />; // examples are optional; the form works without them
}
