import { NextResponse } from "next/server";

// 프론트엔드 자체 헬스체크 (Docker/로드밸런서용).
export function GET() {
  return NextResponse.json({ status: "ok", service: "frontend" });
}
