/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        wechat: {
          sidebar: '#2e2e2e',
          active: '#07c160',
          hover: '#19b158',
          bg: '#f5f5f5',
          chatbg: '#f3f3f3',
          border: '#e7e7e7',
          bubble: '#95ec69',
        }
      }
    },
  },
  plugins: [],
}
