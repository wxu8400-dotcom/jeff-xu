import React, { useRef } from "react";
import { FileText, Film, Image as ImageIcon, UploadCloud, X } from "lucide-react";

interface Props {
  files: File[];
  onFilesChange: (files: File[]) => void;
  productName: string;
  onProductNameChange: (val: string) => void;
  productText: string;
  onProductTextChange: (val: string) => void;
}

export const ProductUploader: React.FC<Props> = ({
  files,
  onFilesChange,
  productName,
  onProductNameChange,
  productText,
  onProductTextChange,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const arr = Array.from(incoming);
    const merged = [...files, ...arr].slice(0, 10);
    onFilesChange(merged);
  };

  const removeFile = (idx: number) => {
    onFilesChange(files.filter((_, i) => i !== idx));
  };

  const renderIcon = (name: string) => {
    const lower = name.toLowerCase();
    if (/\.(jpg|jpeg|png|webp|gif|bmp)$/.test(lower))
      return <ImageIcon className="w-4 h-4 text-sky-400 shrink-0" />;
    if (/\.(mp4|mov|webm|mkv|avi)$/.test(lower))
      return <Film className="w-4 h-4 text-purple-400 shrink-0" />;
    return <FileText className="w-4 h-4 text-amber-400 shrink-0" />;
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            产品名称（选填，用于历史记录分类名；留空由 AI 自动识别）
          </label>
          <input
            type="text"
            value={productName}
            onChange={(e) => onProductNameChange(e.target.value)}
            placeholder="例如：迷你高速冰敷手持风扇 / 磁吸咖啡杯"
            className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-400"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            上传产品资料（支持图片、短视频、PDF、Word、TXT 多选）
          </label>
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles(e.dataTransfer.files);
            }}
            className="cursor-pointer px-3.5 py-2.5 rounded-xl bg-slate-950 border border-dashed border-slate-600 hover:border-sky-400 text-xs sm:text-sm text-slate-300 flex items-center justify-center gap-2 transition"
          >
            <UploadCloud className="w-4 h-4 text-sky-400 shrink-0" />
            <span className="truncate">点击选择或拖入图片 / 视频 / 文档</span>
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept="image/*,video/*,.pdf,.docx,.txt,.md,.csv"
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((f, idx) => (
            <div
              key={`${f.name}-${idx}`}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-xs text-slate-200 max-w-full"
            >
              {renderIcon(f.name)}
              <span className="truncate max-w-[180px]">{f.name}</span>
              <span className="text-slate-400 shrink-0">
                {(f.size / 1024 / 1024 >= 1
                  ? `${(f.size / 1024 / 1024).toFixed(1)}MB`
                  : `${Math.max(1, Math.round(f.size / 1024))}KB`)}
              </span>
              <button
                type="button"
                onClick={() => removeFile(idx)}
                className="text-slate-400 hover:text-rose-400"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-slate-300 mb-1.5">
          产品核心卖点与文字介绍（可补充外观尺寸、材质颜色、目标人群、痛点等）
        </label>
        <textarea
          rows={3}
          value={productText}
          onChange={(e) => onProductTextChange(e.target.value)}
          placeholder="例如：掌心大小磨砂白手持风扇，3秒半导体冰敷降温，USB-C快充续航12小时，主打欧美夏季通勤、户外音乐节、办公桌静音场景..."
          className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-400"
        />
      </div>
    </div>
  );
};
