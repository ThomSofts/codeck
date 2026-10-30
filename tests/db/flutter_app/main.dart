import 'dart:async';
import 'package:flutter/material.dart';
import 'package:hive/hive.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite/sqflite.dart';

// App de teste do Codeck: cria um banco sqflite ('codeck_teste.db'), uma caixa Hive e preferências,
// e mostra o que está no banco (relê a cada 2 s — dá para ver a edição feita pelo Codeck chegar).
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final db = await openDatabase(join(await getDatabasesPath(), 'codeck_teste.db'), version: 1, onCreate: (db, v) async {
    await db.execute('CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, saldo REAL)');
    await db.insert('clientes', {'id': 1, 'nome': 'Ana', 'saldo': 10.5});
    await db.insert('clientes', {'id': 2, 'nome': 'Bruno', 'saldo': 3});
  });
  Hive.init((await getApplicationDocumentsDirectory()).path);
  final box = await Hive.openBox('config');
  await box.put('tema', 'escuro');
  await box.put('versao', 3);
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString('usuario', 'ana');
  await prefs.setInt('abertura', (prefs.getInt('abertura') ?? 0) + 1);
  runApp(App(db: db));
}

class App extends StatefulWidget {
  final Database db;
  const App({super.key, required this.db});
  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  List<Map<String, Object?>> rows = [];
  Timer? t;
  @override
  void initState() {
    super.initState();
    load();
    t = Timer.periodic(const Duration(seconds: 2), (_) => load());
  }
  Future<void> load() async {
    final r = await widget.db.query('clientes', orderBy: 'id');
    if (mounted) setState(() => rows = r);
  }
  @override
  Widget build(BuildContext context) => MaterialApp(home: Scaffold(
      appBar: AppBar(title: const Text('Codeck · banco de teste')),
      body: ListView(children: [for (final r in rows) ListTile(title: Text('${r['nome']}'), subtitle: Text('saldo ${r['saldo']}'))])));
}
