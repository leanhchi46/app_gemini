// file: .cline/rules.mjs

export default {
  // Cấu hình cho Retrieval-Augmented Generation (RAG)
  RAG: {
    include: [
      'src/**',
      'data/**'
    ],
    exclude: [
      '**/__pycache__/**',
      '**/*.txt',
      '__tmp*',
    ],
  },

  // Thêm hướng dẫn tùy chỉnh vào prompt hệ thống của Cline
  prompt: {
    prepend: [
      'Trả lời tôi bằng Tiếng Việt.',
      '---',
      'Đây là một dự án giao dịch tự động bằng Python, tương tác với MetaTrader 5.',
      '---',
      'CẤU TRÚC DỰ ÁN:',
      '- `src/`: Chứa toàn bộ mã nguồn của ứng dụng.',
      '  - `core/`: Logic nghiệp vụ cốt lõi (giao dịch, backtest, các quy tắc no-trade/no-run).',
      '  - `utils/`: Các tiện ích hỗ trợ.',
      '  - `services/`: Các module kết nối dịch vụ bên ngoài.',
      '  - `config/`: Các tệp cấu hình.',
      '  - `prompts/`: Các tệp prompt cho AI.',
      '- `data/`: Chứa dữ liệu của ứng dụng (log giao dịch).',
      '- `scripts/`: Chứa các script chạy riêng lẻ.',
      '---',
      'QUY TẮC CODING:',
      '- Bắt buộc dùng type hints đầy đủ và docstring ngắn gọn cho tất cả các hàm và phương thức.',
      '- Format code bằng `black` trước khi hoàn thành.',
      '- Lint code bằng `ruff` với các rule: E, F, I, B, C90.',
      '- Loại bỏ các comment tiếng Anh. Viết comment nội bộ bằng tiếng Việt để giải thích các logic phức tạp hoặc các tác dụng phụ (side-effect) có thể xảy ra.',
      '---'
    ].join('\n'),
  },
};
