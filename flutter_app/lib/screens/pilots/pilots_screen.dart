import 'package:flutter/material.dart';

class PilotsScreen extends StatelessWidget {
  const PilotsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Пилоты'),
        actions: [
          IconButton(icon: const Icon(Icons.search), onPressed: () {}),
        ],
      ),
      body: const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.people_outline, size: 64, color: Colors.grey),
            SizedBox(height: 16),
            Text('Рейтинг пилотов', style: TextStyle(color: Colors.grey, fontSize: 16)),
            SizedBox(height: 8),
            Text('Будет загружен из API', style: TextStyle(color: Colors.grey, fontSize: 13)),
          ],
        ),
      ),
    );
  }
}
