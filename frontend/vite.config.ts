/// <reference types="vitest" />
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

const REACT_PACKAGES = new Set(['react', 'react-dom', 'scheduler']);

const ADMIN_ANTD_COMPONENTS = new Set(['descriptions', 'progress', 'statistic', 'upload']);

const ANTD_FOUNDATION_PACKAGES = new Set([
  '@ant-design/colors',
  '@ant-design/cssinjs',
  '@ant-design/cssinjs-utils',
  '@ant-design/fast-color',
  '@emotion/hash',
  '@emotion/unitless',
  '@rc-component/util',
  'clsx',
  'is-mobile',
  'react-is',
  'stylis',
]);

function getNodeModulePackage(id: string): string | undefined {
  const normalizedId = id.replaceAll('\\', '/').split('?', 1)[0];
  const marker = '/node_modules/';
  const markerIndex = normalizedId.lastIndexOf(marker);

  if (markerIndex < 0) return undefined;

  const [first, second] = normalizedId.slice(markerIndex + marker.length).split('/');
  if (!first) return undefined;

  return first.startsWith('@') && second ? `${first}/${second}` : first;
}

function getAntdComponent(id: string): string | undefined {
  const normalizedId = id.replaceAll('\\', '/').split('?', 1)[0];
  return normalizedId.match(/\/node_modules\/antd\/(?:es|lib)\/([^/]+)/)?.[1];
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8010';

  return {
    plugins: [react()],
    build: {
      // The shared Ant Design SCC is ~525 kB uncompressed (~158 kB gzip).
      // Admin-only leaf components remain in a separate lazy chunk.
      chunkSizeWarningLimit: 550,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const packageName = getNodeModulePackage(id);
            if (!packageName) return undefined;

            if (packageName === '@ant-design/x') return 'ant-design-x';
            if (REACT_PACKAGES.has(packageName)) return 'react-vendor';
            if (packageName === '@babel/runtime') return 'babel-runtime';
            if (ANTD_FOUNDATION_PACKAGES.has(packageName)) return 'antd-foundation';
            if (packageName === 'antd') {
              const component = getAntdComponent(id);
              return component && ADMIN_ANTD_COMPONENTS.has(component)
                ? 'antd-admin'
                : 'antd-components';
            }

            if (
              packageName.startsWith('@ant-design/') ||
              packageName.startsWith('@rc-component/') ||
              /^rc-[a-z0-9-]+$/i.test(packageName)
            ) {
              return 'antd-runtime';
            }

            return undefined;
          },
        },
      },
    },
    resolve: {
      alias:
        mode === 'test'
          ? [
              {
                // The package's Node entry wraps CommonJS that requires an unmarked ESM file.
                // Use its published ESM subpath under Vitest; production Vite already selects ESM.
                find: /^@ant-design\/icons$/,
                replacement: '@ant-design/icons/es',
              },
            ]
          : [],
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/health': { target: apiTarget, changeOrigin: true },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 4173,
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: true,
      server: {
        deps: {
          inline: ['@ant-design/colors', '@ant-design/icons'],
        },
      },
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json-summary', 'html'],
        include: [
          'src/features/chat-stream/**/*.{ts,tsx}',
          'src/features/admin-*/api/**/*.ts',
          'src/entities/admin-session/model/**/*.ts',
          'src/entities/document/model/**/*.ts',
          'src/entities/evaluation/model/**/*.ts',
          'src/shared/api/**/*.ts',
          'src/shared/lib/**/*.ts',
        ],
        thresholds: {
          lines: 75,
          branches: 65,
          functions: 75,
          statements: 75,
        },
      },
    },
  };
});
