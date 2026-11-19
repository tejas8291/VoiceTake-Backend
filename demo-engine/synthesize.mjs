import { readFile, writeFile } from 'node:fs/promises'
import ESpeakNg from 'espeak-ng'

const [sourcePath, outputPath, speed, voice, language] = process.argv.slice(2)
const text = await readFile(sourcePath, 'utf8')
const variant = voice.includes('+') ? '+' + voice.split('+')[1] : ''
const hindiVoice = 'hi' + variant

// All SSML tags are app-generated. Script text is escaped before substitution.
function mixedScript(input) {
  const escaped = input.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  return '<speak>' + escaped.replace(/[\p{Script=Devanagari}\u200C\u200D]+(?: +[\p{Script=Devanagari}\u200C\u200D]+)*/gu,
    match => `<voice name="${hindiVoice}" xml:lang="hi">${match}</voice>`) + '</speak>'
}

const mixed = language === 'hinglish'
const engine = await ESpeakNg({
  arguments: [
    '-v', language === 'hi' ? hindiVoice : voice,
    '-s', speed,
    '-w', 'take.wav',
    ...(mixed ? ['-m'] : []),
    '--', mixed ? mixedScript(text) : text,
  ],
  print: () => {},
})
await writeFile(outputPath, engine.FS.readFile('take.wav'))
