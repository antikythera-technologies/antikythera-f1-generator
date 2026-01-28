/**
 * TypeScript declarations for SVG imports
 * 
 * This allows importing .svg files as React components when using SVGR
 * 
 * For Next.js, ensure you have @svgr/webpack configured in next.config.js:
 * 
 * webpack(config) {
 *   config.module.rules.push({
 *     test: /\.svg$/,
 *     use: ['@svgr/webpack'],
 *   });
 *   return config;
 * }
 */

declare module '*.svg' {
  import { FC, SVGProps } from 'react';
  const content: FC<SVGProps<SVGSVGElement>>;
  export default content;
}

declare module '*.svg?url' {
  const content: string;
  export default content;
}
