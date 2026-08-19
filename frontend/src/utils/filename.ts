// Имена файлов для скачивания.

// Номер версии в имени файла ставим ПЕРЕД расширением («счёт v1.pdf»).
// Если приклеить его в конец («счёт.pdf v1»), ОС считает расширением « v1» и
// файл перестаёт открываться — из-за этого и правился баг.
//
// База имени — оригинальное имя файла ИМЕННО ЭТОЙ версии (у версий они могут
// отличаться); title документа — запасной путь, если сервер имени не отдал.
export function versionFileName(
  title: string,
  version: { version_number: number; original_filename?: string },
): string {
  const base = version.original_filename || title || 'file'
  const suffix = ` v${version.version_number}`
  const dot = base.lastIndexOf('.')
  // dot > 0, а не >= 0: у имён вида «.env» точка не отделяет расширение.
  return dot > 0 ? base.slice(0, dot) + suffix + base.slice(dot) : base + suffix
}
