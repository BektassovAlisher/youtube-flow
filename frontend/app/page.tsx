import type { VideoListItem } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import Home from "./home";

export default async function HomePage() {
  const { data } = await serverApi<VideoListItem[]>("videos?limit=3");
  return <Home examples={data?.filter((v) => v.status === "ready") ?? []} />; // examples are optional; the form works without them
}
