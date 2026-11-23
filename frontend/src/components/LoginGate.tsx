import React, { useState } from "react";
import { Lock, Radar, ShieldCheck } from "lucide-react";
import { api } from "../api/client";

interface Props {
  onSuccess: () => void;
}

export const LoginGate: React.FC<Props> = ({ onSuccess }) => {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError("请输入访问密码");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.login(password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "密码错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-slate-900/90 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-sky-500/15 border border-sky-500/30 mx-auto mb-5">
          <Radar className="w-7 h-7 text-sky-400" />
        </div>
        <h1 className="text-xl sm:text-2xl font-bold text-center text-white mb-1">
          短视频爆款扫描雷达
        </h1>
        <p className="text-xs sm:text-sm text-slate-400 text-center mb-6">
          TikTok · Instagram Reels · YouTube Shorts
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              专属访问密码（防公网盗刷 API 余额）
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入你在环境变量设置的访问密码"
                autoFocus
                className="w-full pl-10 pr-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-400 text-sm"
              />
            </div>
          </div>

          {error && (
            <div className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-60 text-slate-950 font-semibold text-sm transition flex items-center justify-center gap-2"
          >
            <ShieldCheck className="w-4 h-4" />
            {loading ? "验证中..." : "解锁进入工作台"}
          </button>
        </form>
      </div>
    </div>
  );
};
