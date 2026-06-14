import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 이미지를 가볍게: 빌드 결과를 standalone 으로 묶습니다.
  output: "standalone",
};

export default nextConfig;
