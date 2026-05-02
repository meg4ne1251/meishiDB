export default function OfflinePage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center justify-center gap-4 py-24 text-center">
      <h1 className="text-xl font-semibold">オフラインです</h1>
      <p className="text-sm text-muted-foreground">
        ネットワーク接続を確認してから再読み込みしてください。
      </p>
    </div>
  );
}
