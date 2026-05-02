"use client";

import { useRef, useState } from "react";
import { Camera, ImagePlus } from "lucide-react";

import { Button } from "@/components/ui/button";

interface Props {
  onPicked: (file: File, previewUrl: string) => void;
  disabled?: boolean;
  label?: string;
}

/**
 * モバイルでは `capture="environment"` でリアカメラが起動する。
 * デスクトップではファイル選択ダイアログ。
 *
 * MediaStream（getUserMedia）は HTTPS 必須かつ UX が複雑なので、
 * MVP では `<input type=file capture>` のみに割り切る。
 */
export function CardImageCapture({ onPicked, disabled, label = "名刺を撮影" }: Props) {
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);

  function handle(file: File) {
    const url = URL.createObjectURL(file);
    setPreview(url);
    onPicked(file, url);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={disabled}
          onClick={() => cameraRef.current?.click()}
        >
          <Camera className="mr-2 h-4 w-4" />
          {label}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => fileRef.current?.click()}
        >
          <ImagePlus className="mr-2 h-4 w-4" />
          ファイルから選択
        </Button>
      </div>

      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handle(f);
          e.currentTarget.value = "";
        }}
      />
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handle(f);
          e.currentTarget.value = "";
        }}
      />

      {preview && (
        <div className="overflow-hidden rounded-lg border border-border">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={preview} alt="preview" className="max-h-72 w-full object-contain bg-black/40" />
        </div>
      )}
    </div>
  );
}
