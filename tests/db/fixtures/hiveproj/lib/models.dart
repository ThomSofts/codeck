import 'package:hive/hive.dart';

@HiveType(typeId: 1)
class Cliente {
  @HiveField(0)
  final String nome;
  @HiveField(1)
  final double saldo;
  @HiveField(2)
  final Status status;
  @HiveField(3)
  final DateTime criado;
  Cliente(this.nome, this.saldo, this.status, this.criado);
}

@HiveType(typeId: 2)
enum Status {
  @HiveField(0)
  ativo,
  @HiveField(1)
  bloqueado,
}

// o que o build_runner gera (escrito à mão para não precisar do gerador)
class ClienteAdapter extends TypeAdapter<Cliente> {
  @override
  final int typeId = 1;
  @override
  Cliente read(BinaryReader r) {
    final n = r.readByte();
    final f = <int, dynamic>{for (var i = 0; i < n; i++) r.readByte(): r.read()};
    return Cliente(f[0] as String, f[1] as double, f[2] as Status, f[3] as DateTime);
  }
  @override
  void write(BinaryWriter w, Cliente o) {
    w..writeByte(4)..writeByte(0)..write(o.nome)..writeByte(1)..write(o.saldo)..writeByte(2)..write(o.status)..writeByte(3)..write(o.criado);
  }
}

class StatusAdapter extends TypeAdapter<Status> {
  @override
  final int typeId = 2;
  @override
  Status read(BinaryReader r) => Status.values[r.readByte()];
  @override
  void write(BinaryWriter w, Status o) => w.writeByte(o.index);
}
