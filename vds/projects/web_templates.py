"""Dateien der Web-Vorlagen (React/Vite, Vue/Vite, Next.js, Nuxt) und PHP. Platzhalter: __NAME__, __IDLOWER__ (npm-tauglicher Paketname)."""

DEV = "[ -d node_modules ] || npm install; npm run dev"
HTML = ('<!doctype html>\n<html lang="de">\n  <head>\n    <meta charset="UTF-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        '    <title>__NAME__</title>\n  </head>\n  <body>\n    <div id="__ROOT__"></div>\n    <script type="module" src="/src/__MAIN__"></script>\n  </body>\n</html>\n')


def _html(root_id: str, main: str) -> str:
    return HTML.replace("__ROOT__", root_id).replace("__MAIN__", main)


VITE_TSCONFIG = ('{\n  "compilerOptions": {\n    "target": "ES2020",\n    "useDefineForClassFields": true,\n    "lib": ["ES2020", "DOM", "DOM.Iterable"],\n    "module": "ESNext",\n'
                 '    "skipLibCheck": true,\n    "moduleResolution": "bundler",\n    "resolveJsonModule": true,\n    "isolatedModules": true,\n    "noEmit": true,\n'
                 '    "jsx": "react-jsx",\n    "strict": true\n  },\n  "include": ["src"]\n}\n')

REACT_FILES = {
    "package.json": '{\n  "name": "__IDLOWER__",\n  "private": true,\n  "version": "0.0.0",\n  "type": "module",\n  "scripts": {\n    "dev": "vite",\n'
                    '    "build": "tsc --noEmit && vite build",\n    "preview": "vite preview"\n  },\n  "dependencies": {\n    "react": "^19.0.0",\n'
                    '    "react-dom": "^19.0.0"\n  },\n  "devDependencies": {\n    "@types/react": "^19.0.0",\n    "@types/react-dom": "^19.0.0",\n'
                    '    "@vitejs/plugin-react": "^4.3.0",\n    "typescript": "^5.6.0",\n    "vite": "^6.0.0"\n  }\n}\n',
    "index.html": _html("root", "main.tsx"),
    "vite.config.ts": 'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\nexport default defineConfig({ plugins: [react()] });\n',
    "tsconfig.json": VITE_TSCONFIG,
    "src/main.tsx": 'import { StrictMode } from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App";\n\n'
                    'createRoot(document.getElementById("root")!).render(\n  <StrictMode>\n    <App />\n  </StrictMode>,\n);\n',
    "src/App.tsx": 'import { useState } from "react";\nimport Form1 from "./Form1";\n\nexport default function App() {\n  const [msg, setMsg] = useState("");\n'
                   '  return (\n    <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>\n      <h1>__NAME__</h1>\n'
                   '      <Form1 onButton1Clicked={() => setMsg("Button geklickt!")} />\n      <p>{msg}</p>\n    </div>\n  );\n}\n',
}

VUE_FILES = {
    "package.json": '{\n  "name": "__IDLOWER__",\n  "private": true,\n  "version": "0.0.0",\n  "type": "module",\n  "scripts": {\n    "dev": "vite",\n'
                    '    "build": "vue-tsc --noEmit && vite build",\n    "preview": "vite preview"\n  },\n  "dependencies": {\n    "vue": "^3.5.0"\n  },\n'
                    '  "devDependencies": {\n    "@vitejs/plugin-vue": "^5.2.0",\n    "typescript": "^5.6.0",\n    "vite": "^6.0.0",\n    "vue-tsc": "^2.1.0"\n  }\n}\n',
    "index.html": _html("app", "main.ts"),
    "vite.config.ts": 'import { defineConfig } from "vite";\nimport vue from "@vitejs/plugin-vue";\n\nexport default defineConfig({ plugins: [vue()] });\n',
    "tsconfig.json": VITE_TSCONFIG.replace('"jsx": "react-jsx",', '"jsx": "preserve",').replace('"include": ["src"]', '"include": ["src/**/*.ts", "src/**/*.vue"]'),
    "src/env.d.ts": '/// <reference types="vite/client" />\n',
    "src/main.ts": 'import { createApp } from "vue";\nimport App from "./App.vue";\n\ncreateApp(App).mount("#app");\n',
    "src/App.vue": '<script setup lang="ts">\nimport { ref } from "vue";\nimport Form1 from "./Form1.vue";\n\nconst msg = ref("");\n</script>\n\n<template>\n'
                   '  <div style="padding: 24px; font-family: system-ui, sans-serif">\n    <h1>__NAME__</h1>\n    <Form1 @button1Clicked="msg = \'Button geklickt!\'" />\n'
                   '    <p>{{ msg }}</p>\n  </div>\n</template>\n',
}

NEXT_FILES = {
    "package.json": '{\n  "name": "__IDLOWER__",\n  "private": true,\n  "version": "0.1.0",\n  "scripts": {\n    "dev": "next dev",\n    "build": "next build",\n'
                    '    "start": "next start"\n  },\n  "dependencies": {\n    "next": "^15.0.0",\n    "react": "^19.0.0",\n    "react-dom": "^19.0.0"\n  },\n'
                    '  "devDependencies": {\n    "@types/node": "^22.0.0",\n    "@types/react": "^19.0.0",\n    "@types/react-dom": "^19.0.0",\n    "typescript": "^5.6.0"\n  }\n}\n',
    "next.config.mjs": "/** @type {import('next').NextConfig} */\nconst nextConfig = {};\n\nexport default nextConfig;\n",
    "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2017",\n    "lib": ["dom", "dom.iterable", "esnext"],\n    "allowJs": true,\n    "skipLibCheck": true,\n'
                     '    "strict": true,\n    "noEmit": true,\n    "esModuleInterop": true,\n    "module": "esnext",\n    "moduleResolution": "bundler",\n'
                     '    "resolveJsonModule": true,\n    "isolatedModules": true,\n    "jsx": "preserve",\n    "incremental": true,\n    "plugins": [{ "name": "next" }]\n  },\n'
                     '  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],\n  "exclude": ["node_modules"]\n}\n',
    "app/layout.tsx": 'export const metadata = { title: "__NAME__" };\n\nexport default function RootLayout({ children }: { children: React.ReactNode }) {\n'
                      '  return (\n    <html lang="de">\n      <body>{children}</body>\n    </html>\n  );\n}\n',
    "app/page.tsx": '"use client";\n\nimport { useState } from "react";\nimport Form1 from "../components/Form1";\n\nexport default function Home() {\n'
                    '  const [msg, setMsg] = useState("");\n  return (\n    <main style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>\n      <h1>__NAME__</h1>\n'
                    '      <Form1 onButton1Clicked={() => setMsg("Button geklickt!")} />\n      <p>{msg}</p>\n    </main>\n  );\n}\n',
}

NUXT_FILES = {
    "package.json": '{\n  "name": "__IDLOWER__",\n  "private": true,\n  "type": "module",\n  "scripts": {\n    "dev": "nuxt dev",\n    "build": "nuxt build",\n'
                    '    "generate": "nuxt generate",\n    "preview": "nuxt preview",\n    "postinstall": "nuxt prepare"\n  },\n  "dependencies": {\n'
                    '    "nuxt": "^3.14.0",\n    "vue": "^3.5.0",\n    "vue-router": "^4.4.0"\n  }\n}\n',
    "nuxt.config.ts": 'export default defineNuxtConfig({\n  compatibilityDate: "2024-11-01",\n  devtools: { enabled: false },\n});\n',
    "tsconfig.json": '{\n  "extends": "./.nuxt/tsconfig.json"\n}\n',
    "app.vue": '<script setup lang="ts">\nconst msg = ref("");\n</script>\n\n<template>\n  <div style="padding: 24px; font-family: system-ui, sans-serif">\n'
               '    <h1>__NAME__</h1>\n    <Form1 @button1Clicked="msg = \'Button geklickt!\'" />\n    <p>{{ msg }}</p>\n  </div>\n</template>\n',
}

PHP_CONSOLE = '<?php\n\ndeclare(strict_types=1);\n\nfunction greet(string $name): string\n{\n    return "Hallo, {$name}!";\n}\n\necho greet("__NAME__"), PHP_EOL;\n'
PHP_WEB = {
    "public/index.php": '<?php\n\ndeclare(strict_types=1);\n\nrequire __DIR__ . \'/../src/Greeter.php\';\n\n$name = trim($_POST[\'name\'] ?? \'\');\n$greeter = new Greeter();\n?>\n'
                        '<!doctype html>\n<html lang="de">\n<head>\n  <meta charset="utf-8">\n  <title>__NAME__</title>\n</head>\n<body style="font-family: system-ui, sans-serif; padding: 24px">\n'
                        '  <h1>__NAME__</h1>\n  <form method="post">\n    <input name="name" placeholder="Dein Name" value="<?= htmlspecialchars($name) ?>">\n'
                        '    <button>Begrüßen</button>\n  </form>\n  <?php if ($name !== \'\'): ?>\n    <p><?= htmlspecialchars($greeter->greet($name)) ?></p>\n  <?php endif; ?>\n</body>\n</html>\n',
    "src/Greeter.php": '<?php\n\ndeclare(strict_types=1);\n\nclass Greeter\n{\n    public function greet(string $name): string\n    {\n        return "Hallo, {$name}!";\n    }\n}\n',
}
