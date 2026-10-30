/**
 * Ponte Drive do Estudo IA (Google Apps Script).
 *
 * Roda dentro da conta Google do Matheus e deixa a VPS:
 *   - listar as aulas da pasta "Aulas" e baixar os arquivos delas;
 *   - salvar os pacotes gerados em "Aprofundamento das Aulas".
 *
 * Segurança:
 *   - todo pedido precisa da chave secreta (propriedade CHAVE do script);
 *   - leitura só dentro de "Aulas" e de "Aprofundamento das Aulas"; escrita
 *     só dentro de "Aprofundamento das Aulas". Nenhuma outra pasta é tocada.
 *
 * Como publicar: Implantar → Nova implantação → App da Web →
 *   Executar como: Eu · Quem pode acessar: Qualquer pessoa.
 */

const PASTA_AULAS = '1vLaUqfLpc_PZps0P-h9iMbZMsh3v-yzk';
const PASTA_APROFUNDAMENTO = '1Lx8TWsy93VQB7Dfpgf4r6wS6wUaJZOSc';

function responder_(dados) {
  return ContentService.createTextOutput(JSON.stringify(dados))
    .setMimeType(ContentService.MimeType.JSON);
}

function conferirChave_(chave) {
  const certa = PropertiesService.getScriptProperties().getProperty('CHAVE');
  if (!certa || chave !== certa) throw new Error('chave inválida');
}

/** Confere se o arquivo está dentro de "Aulas" ou de "Aprofundamento das Aulas". */
function estaDentroDasPastas_(arquivo) {
  const permitidas = [PASTA_AULAS, PASTA_APROFUNDAMENTO];
  const visitar = [arquivo.getParents()];
  for (let passos = 0; visitar.length && passos < 10; passos++) {
    const pais = visitar.shift();
    while (pais.hasNext()) {
      const pai = pais.next();
      if (permitidas.indexOf(pai.getId()) >= 0) return true;
      visitar.push(pai.getParents());
    }
  }
  return false;
}

/** Lista "Aprofundamento das Aulas": matérias → aulas → arquivos (o que já foi processado). */
function listarProcessadas_() {
  const materias = [];
  const pastasMateria = DriveApp.getFolderById(PASTA_APROFUNDAMENTO).getFolders();
  while (pastasMateria.hasNext()) {
    const m = pastasMateria.next();
    const aulas = [];
    const pastasAula = m.getFolders();
    while (pastasAula.hasNext()) {
      const a = pastasAula.next();
      const arquivos = [];
      const itens = a.getFiles();
      while (itens.hasNext()) {
        const f = itens.next();
        arquivos.push({ id: f.getId(), nome: f.getName(), tipo: f.getMimeType(), tamanho: f.getSize() });
      }
      aulas.push({ id: a.getId(), nome: a.getName(), criada: a.getDateCreated().toISOString(), arquivos: arquivos });
    }
    materias.push({ nome: m.getName(), aulas: aulas });
  }
  return materias;
}

function listarAulas_() {
  const aulas = [];
  const pastas = DriveApp.getFolderById(PASTA_AULAS).getFolders();
  while (pastas.hasNext()) {
    const pasta = pastas.next();
    const arquivos = [];
    const itens = pasta.getFiles();
    while (itens.hasNext()) {
      const a = itens.next();
      arquivos.push({ id: a.getId(), nome: a.getName(), tipo: a.getMimeType(), tamanho: a.getSize() });
    }
    aulas.push({ id: pasta.getId(), nome: pasta.getName(), criada: pasta.getDateCreated().toISOString(), arquivos: arquivos });
  }
  return aulas;
}

function baixar_(id) {
  const arquivo = DriveApp.getFileById(id);
  if (!estaDentroDasPastas_(arquivo)) throw new Error('arquivo fora das pastas permitidas');
  return {
    nome: arquivo.getName(),
    tipo: arquivo.getMimeType(),
    base64: Utilities.base64Encode(arquivo.getBlob().getBytes()),
  };
}

/** Pega (ou cria) uma subpasta pelo nome. */
function subpasta_(pai, nome) {
  const existentes = pai.getFoldersByName(nome);
  return existentes.hasNext() ? existentes.next() : pai.createFolder(nome);
}

function salvar_(dados) {
  let pasta = DriveApp.getFolderById(PASTA_APROFUNDAMENTO);
  (dados.caminho || []).forEach(function (nome) { pasta = subpasta_(pasta, nome); });
  // Se já existe um arquivo com o mesmo nome, ele vai para a lixeira (versão nova substitui).
  const antigos = pasta.getFilesByName(dados.nome);
  while (antigos.hasNext()) antigos.next().setTrashed(true);
  const blob = Utilities.newBlob(Utilities.base64Decode(dados.base64), dados.tipo, dados.nome);
  const criado = pasta.createFile(blob);
  return { id: criado.getId(), url: criado.getUrl() };
}

function doGet(e) {
  try {
    conferirChave_(e.parameter.chave);
    if (e.parameter.acao === 'listar') return responder_({ ok: true, aulas: listarAulas_() });
    if (e.parameter.acao === 'processadas') return responder_({ ok: true, materias: listarProcessadas_() });
    if (e.parameter.acao === 'baixar') return responder_({ ok: true, arquivo: baixar_(e.parameter.id) });
    if (e.parameter.acao === 'ping') return responder_({ ok: true });
    throw new Error('ação desconhecida');
  } catch (erro) {
    return responder_({ ok: false, erro: String(erro.message || erro) });
  }
}

function doPost(e) {
  try {
    const dados = JSON.parse(e.postData.contents);
    conferirChave_(dados.chave);
    if (dados.acao === 'salvar') return responder_({ ok: true, arquivo: salvar_(dados) });
    throw new Error('ação desconhecida');
  } catch (erro) {
    return responder_({ ok: false, erro: String(erro.message || erro) });
  }
}

/** Rode esta função uma vez no editor para autorizar o acesso ao Drive. */
function autorizar() {
  Logger.log(DriveApp.getFolderById(PASTA_AULAS).getName());
  Logger.log(DriveApp.getFolderById(PASTA_APROFUNDAMENTO).getName());
}
