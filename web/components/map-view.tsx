"use client";

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type { CardGeoPoint } from "@/lib/types";

// セルフホスト純度・プライバシー優先のため、タイルサーバは明示設定を必須にする。
// 既定では外部へタイル要求を送らない（未設定なら下のメッセージを出すだけ）。
// 自前 tileserver-gl 等を建てて NEXT_PUBLIC_MAP_TILE_URL に URL を設定する。
// （あえて公開 OSM を使う場合も同変数に指定する＝外部送信は明示的な選択になる）
const TILE_URL = process.env.NEXT_PUBLIC_MAP_TILE_URL ?? "";

// 初期表示（日本のおおよそ中心）
const DEFAULT_CENTER: [number, number] = [138.0, 38.0];
const DEFAULT_ZOOM = 4;

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

export function MapView({ points }: { points: CardGeoPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  // マップは一度だけ生成する。タイル未設定なら外部へ何も要求しない。
  useEffect(() => {
    if (!TILE_URL || !containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: [TILE_URL],
            tileSize: 256,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // points が変わるたびにマーカーを貼り直し、範囲にフィットする
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (points.length === 0) return;

    const bounds = new maplibregl.LngLatBounds();
    for (const p of points) {
      const popupHtml = `
        <div style="min-width:160px;font-size:13px;line-height:1.4">
          <strong>${escapeHtml(p.person_name || "(無題)")}</strong><br/>
          ${p.company ? `<span>${escapeHtml(p.company)}</span><br/>` : ""}
          ${p.address ? `<span style="color:#666">${escapeHtml(p.address)}</span><br/>` : ""}
          <a href="/cards/${p.id}" style="color:#2563eb">詳細を開く →</a>
        </div>`;
      const marker = new maplibregl.Marker({ color: p.shared ? "#a855f7" : "#2563eb" })
        .setLngLat([p.longitude, p.latitude])
        .setPopup(new maplibregl.Popup({ offset: 24 }).setHTML(popupHtml))
        .addTo(map);
      markersRef.current.push(marker);
      bounds.extend([p.longitude, p.latitude]);
    }

    if (points.length === 1) {
      map.flyTo({ center: [points[0].longitude, points[0].latitude], zoom: 14 });
    } else {
      map.fitBounds(bounds, { padding: 64, maxZoom: 14, duration: 600 });
    }
  }, [points]);

  if (!TILE_URL) {
    return (
      <div className="flex h-full w-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        <div className="max-w-sm">
          地図タイルサーバが未設定です。
          <br />
          セルフホストのタイルサーバ（tileserver-gl 等）を建て、
          <code className="mx-1 rounded bg-muted px-1 py-0.5 text-xs">
            NEXT_PUBLIC_MAP_TILE_URL
          </code>
          に設定してください。
        </div>
      </div>
    );
  }

  return <div ref={containerRef} className="h-full w-full" />;
}
