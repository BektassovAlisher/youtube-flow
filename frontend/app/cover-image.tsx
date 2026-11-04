"use client";

import { useEffect, useRef, useState } from "react";

// A cover that turns into a plain card with the site's name when there is no picture or it fails to load
// (many sites forbid embedding their images). Errors that happen before hydration are caught by the effect.
export default function CoverImage({ src, label, lazy = true }: { src: string | null | undefined; label: string; lazy?: boolean }) {
  const [failed, setFailed] = useState(false);
  const img = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (img.current?.complete && img.current.naturalWidth === 0) setFailed(true);
  }, [src]);

  if (!src || failed)
    return (
      <span className="thumb thumb-placeholder" aria-hidden>
        {label}
      </span>
    );
  return (
    <img
      ref={img}
      className="thumb"
      src={src}
      alt=""
      loading={lazy ? "lazy" : undefined}
      fetchPriority={lazy ? undefined : "high"}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
